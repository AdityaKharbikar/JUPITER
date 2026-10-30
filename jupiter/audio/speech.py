from ..common import *


class SpeechMixin:
    def setup_audio_models(self):
        """Pre-load audio models for speed — GPU first, CPU fallback."""
        if whisper_available:
            print("Loading Whisper model...")
            try:
                self.whisper_model = WhisperModel(self.whisper_model_size, device="cuda", compute_type="float16")
                # Warm-up: missing cuBLAS/cuDNN DLLs only blow up on the FIRST
                # real inference, not when the model loads. Run one second of
                # silence now so a broken GPU falls back to CPU at startup
                # rather than on your first spoken command.
                import numpy as _np
                list(self.whisper_model.transcribe(
                    _np.zeros(self.sample_rate, dtype="float32"), beam_size=1, language="en"
                )[0])
                self.whisper_device = "cuda"
                print("Whisper ready (GPU).")
            except Exception as e:
                print(f"[Whisper GPU Error] {e}")
                print("Falling back to CPU...")
                try:
                    self.whisper_model = WhisperModel(self.whisper_model_size, device="cpu", compute_type="int8", cpu_threads=self._cpu_threads())
                    self.whisper_device = "cpu"
                    print("Whisper ready (CPU).")
                except Exception as e2:
                    print(f"[Whisper CPU Error] {e2}")
        if piper_available:
            model_path = os.path.join(self.project_root, "en_US-lessac-medium.onnx")
            if os.path.exists(model_path):
                self.piper_voice = PiperVoice.load(model_path)
                print("Piper TTS ready.")
        self._load_stop_model()

    @staticmethod
    def _cpu_threads() -> int:
        return max(2, min(8, os.cpu_count() or 4))

    def _init_speech_engine(self):
        self._tts_q = queue.Queue()            # (text, generation)
        self._play_q = queue.Queue()           # (kind, payload, rate, text, generation)
        self._speech_gen = 0                   # bumped on every interrupt; older items are dropped
        self._pending = 0                      # sentences queued or playing
        self._pending_cv = threading.Condition()
        self._interrupted = threading.Event()  # set by an interrupt, cleared when the next turn starts
        self._duck = threading.Event()         # "pause the audio, I think I hear you"
        self._playing = threading.Event()      # audio is coming out of the speakers right now
        self._speech_threads = []
        self._out_stream = None
        self._out_rate = None
        self._stream_failed = False
        self._native_proc = None
        self._syn_config = None
        self._barge_thread = None
        self._barge_stop = None
        self._stop_model = None

    def _ensure_speech_threads(self):
        if self._speech_threads:
            return
        self._speech_threads = [
            threading.Thread(target=self._synth_loop, name="jupiter-synth", daemon=True),
            threading.Thread(target=self._play_loop, name="jupiter-play", daemon=True),
        ]
        for t in self._speech_threads:
            t.start()

    def speak(self, text, wait: bool = True):
        """Say something. Blocks until spoken unless wait=False.

        ``None`` is treated as no response rather than being printed as a
        literal answer. This is a final safety net for services that use
        side-effect speech and return ``None``.
        """
        if text is None:
            return
        text = str(text)
        print(f"JUPITER: {text}")
        self._last_response = text
        if not text.strip():
            return
        if self._interrupted.is_set():
            return
        self._ensure_speech_threads()
        with self._pending_cv:
            self._pending += 1
            gen = self._speech_gen
        self._tts_q.put((str(text), gen))
        self._start_barge_monitor()
        if wait:
            self.wait_speech_done()

    def wait_speech_done(self):
        """Block until everything queued has been spoken, or dropped by an interrupt."""
        with self._pending_cv:
            while self._pending > 0:
                self._pending_cv.wait(timeout=0.25)
                if self._pending > 0 and self._speech_threads and not all(
                    t.is_alive() for t in self._speech_threads
                ):
                    self._pending = 0   # a worker died; don't hang the main loop
                    break

    def _speech_item_done(self):
        with self._pending_cv:
            self._pending = max(0, self._pending - 1)
            self._pending_cv.notify_all()

    def _discard_item(self, item):
        """Throw away a synthesised item that was interrupted before playing."""
        if item and item[0] == "wav":
            try:
                os.remove(item[1])
            except OSError:
                pass

    def _synth_loop(self):
        while True:
            text, gen = self._tts_q.get()
            try:
                if gen != self._speech_gen:
                    self._speech_item_done()
                    continue
                item = self._synthesize(text)
                if gen != self._speech_gen:
                    self._discard_item(item)
                    self._speech_item_done()
                    continue
                self._play_q.put((item[0], item[1], item[2], text, gen))
            except Exception as e:
                print(f"[TTS Error] {e}")
                self._speech_item_done()

    def _synthesize(self, text):
        """-> (kind, payload, rate). kind is "pcm" (int16 samples), "wav" (a temp
        file, the old route) or "text" (no Piper: use the OS voice)."""
        if piper_available and hasattr(self, "piper_voice"):
            try:
                if self._syn_config is None:
                    self._syn_config = SynthesisConfig(length_scale=getattr(self, "tts_length_scale", 0.70))
                if audio_input_available and self.tts_in_memory and not self._stream_failed:
                    buf = io.BytesIO()
                    with wave.open(buf, "wb") as wf:
                        self.piper_voice.synthesize_wav(text, wf, syn_config=self._syn_config)
                    buf.seek(0)
                    with wave.open(buf, "rb") as wf:
                        rate = wf.getframerate()
                        raw = wf.readframes(wf.getnframes())
                    return "pcm", np.frombuffer(raw, dtype=np.int16).copy(), rate
                path = self._tmp_wav_path()
                with wave.open(path, "wb") as wf:
                    self.piper_voice.synthesize_wav(text, wf, syn_config=self._syn_config)
                return "wav", path, None
            except Exception as e:
                print(f"[Piper Error] {e}")
        return "text", None, None

    def _tmp_wav_path(self) -> str:
        base = getattr(self, "data_dir", os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(base, f"tts_{os.getpid()}_{time.time_ns()}.wav")

    def _play_loop(self):
        while True:
            kind, payload, rate, text, gen = self._play_q.get()
            try:
                if gen != self._speech_gen:
                    self._discard_item((kind, payload))
                    continue
                self._playing.set()
                if kind == "pcm":
                    try:
                        self._play_pcm(payload, rate, gen)
                    except Exception as e:
                        # No output device / driver quirk: fall back to the old
                        # temp-wav route for this sentence and every later one.
                        print(f"[Audio Out Error] {e} - falling back to wav playback")
                        self._stream_failed = True
                        self._close_out_stream()
                        self._play_pcm_via_wav(payload, rate, gen)
                elif kind == "wav":
                    try:
                        self._play_wav(payload, gen)
                    finally:
                        try:
                            os.remove(payload)
                        except OSError:
                            pass
                else:
                    self._speak_native_fallback(text)
            except Exception as e:
                print(f"[TTS Play Error] {e}")
            finally:
                self._playing.clear()
                self._speech_item_done()

    def _get_out_stream(self, rate):
        if self._out_stream is not None and self._out_rate == rate:
            return self._out_stream
        self._close_out_stream()
        with _AUDIO_OPEN_LOCK:
            stream = sd.OutputStream(samplerate=rate, channels=1, dtype="int16", latency="low")
            stream.start()
        self._out_stream, self._out_rate = stream, rate
        return stream

    def _close_out_stream(self):
        stream, self._out_stream, self._out_rate = self._out_stream, None, None
        if stream is not None:
            try:
                stream.abort()
                stream.close()
            except Exception:
                pass

    def _play_pcm(self, pcm, rate, gen):
        """Feed samples to the sound card ~23 ms at a time, so an interrupt (or a
        "duck" while the stop-listener decides what it heard) takes effect almost
        immediately instead of after the whole sentence."""
        stream = self._get_out_stream(rate)
        block = 512
        n = len(pcm)
        i = 0
        while i < n:
            if gen != self._speech_gen:
                try:
                    stream.abort()    # drop whatever is still buffered...
                    stream.start()    # ...and be ready for the next thing to say
                except Exception:
                    self._close_out_stream()
                return
            if self._duck.is_set():
                t0 = time.monotonic()
                while self._duck.is_set() and gen == self._speech_gen and time.monotonic() - t0 < 4.0:
                    time.sleep(0.02)
                self._duck.clear()    # never leave it stuck on
                continue
            stream.write(pcm[i:i + block].reshape(-1, 1))
            i += block

    def _play_pcm_via_wav(self, pcm, rate, gen=None):
        path = self._tmp_wav_path()
        try:
            with wave.open(path, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(rate)
                wf.writeframes(pcm.tobytes())
            self._play_wav(path, gen)
        finally:
            try:
                os.remove(path)
            except OSError:
                pass

    def interrupt_speech(self):
        """Cut Jupiter off right now: bump the generation (the play thread
        notices within one 23 ms block and everything queued is dropped), kill
        any fallback TTS process, and flag the turn as interrupted so neither
        the rest of the answer nor the rest of the LLM stream gets spoken."""
        self._interrupted.set()
        with self._pending_cv:
            self._speech_gen += 1
        self._duck.clear()
        proc = self._native_proc
        if proc is not None:
            try:
                proc.terminate()
            except Exception:
                pass
        for q in (self._tts_q, self._play_q):
            while True:
                try:
                    item = q.get_nowait()
                except queue.Empty:
                    break
                if q is self._play_q:
                    self._discard_item(item)
                self._speech_item_done()

    def _wav_seconds(self, path: str) -> float:
        try:
            with wave.open(path, "rb") as wf:
                return wf.getnframes() / float(wf.getframerate() or 22050)
        except Exception:
            return 30.0

    def _play_wav(self, path: str, gen=None):
        """Play a wav file, one real command per OS - never a shell string.

        It must stay INTERRUPTIBLE: the old Windows route used a blocking
        winsound.PlaySound(), which nothing can cancel, so a spoken "stop" /
        Esc was ignored until the sentence ended (this was the "sometimes
        doesn't stop on barge-in" bug). Now playback is asynchronous and we
        poll for an interrupt, purging the sound the moment one arrives."""
        def cancelled() -> bool:
            return self._interrupted.is_set() or (gen is not None and gen != self._speech_gen)

        if sys.platform == "win32":
            winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC)
            deadline = time.monotonic() + self._wav_seconds(path) + 0.15
            stopped = False
            while time.monotonic() < deadline:
                if cancelled():
                    stopped = True
                    break
                time.sleep(0.02)
            if stopped:
                winsound.PlaySound(None, winsound.SND_PURGE)   # cut it off right now
            return
        if sys.platform == "darwin":
            self._run_tts_process(["afplay", path])
            return
        for player in ("paplay", "aplay", "ffplay"):
            if shutil.which(player):
                args = ([player, "-nodisp", "-autoexit", "-loglevel", "quiet", path]
                        if player == "ffplay" else [player, path])
                self._run_tts_process(args)     # killable, unlike subprocess.run
                return
        print("[Audio Playback] No player found (tried paplay/aplay/ffplay). Text shown above.")

    def _run_tts_process(self, argv, timeout: float = 30.0):
        """Run an OS speech command we can KILL, so "stop" works here too."""
        proc = subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self._native_proc = proc
        try:
            deadline = time.monotonic() + timeout
            while proc.poll() is None:
                if self._interrupted.is_set() or time.monotonic() > deadline:
                    proc.terminate()
                    break
                time.sleep(0.03)
        finally:
            self._native_proc = None

    def _speak_native_fallback(self, text: str):
        """OS built-in TTS when Piper isn't available. Only ever runs a fixed
        argv list - the text is a separate array element (or, for PowerShell, a
        single-quoted string whose only special character, the quote, is
        doubled), never interpolated into a shell command line."""
        if sys.platform == "win32":
            try:
                safe_text = text.replace("'", "''")
                self._run_tts_process([
                    "powershell", "-NoProfile", "-Command",
                    "Add-Type -AssemblyName System.Speech; "
                    f"$s=(New-Object System.Speech.Synthesis.SpeechSynthesizer); $s.Rate=1; $s.Speak('{safe_text}')"
                ])
                return
            except Exception as e:
                print(f"[Fallback TTS Error] {e}")
        elif sys.platform == "darwin":
            try:
                self._run_tts_process(["say", text])
                return
            except Exception as e:
                print(f"[Fallback TTS Error] {e}")
        else:
            for player in ("espeak-ng", "espeak", "spd-say"):
                if shutil.which(player):
                    try:
                        self._run_tts_process([player, text])
                        return
                    except Exception as e:
                        print(f"[Fallback TTS Error] {e}")
                    break
        print(f"[Text Only] {text}")
