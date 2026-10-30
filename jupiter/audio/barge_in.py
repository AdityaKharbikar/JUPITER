from ..common import *


class BargeInMixin:
    def _barge_ready(self) -> bool:
        return (
            self.barge_in_enabled
            and audio_input_available
            and self._voice_possible()
            and self.input_mode == "voice"
            and self.listen_mode == LISTEN_ACTIVE
        )

    def _start_barge_monitor(self):
        if not self._barge_ready():
            return
        t = self._barge_thread
        # A monitor that is already winding down (its stop event is set) must
        # not block a new one, otherwise the next sentence is left with no
        # listener at all ("sometimes doesn't stop on barge-in").
        if t is not None and t.is_alive() and not (self._barge_stop is not None and self._barge_stop.is_set()):
            return
        stop_evt = threading.Event()
        self._barge_stop = stop_evt
        self._barge_thread = threading.Thread(
            target=self._barge_in_loop, args=(stop_evt,), name="jupiter-barge-in", daemon=True
        )
        self._barge_thread.start()

    def _stop_barge_monitor(self):
        """Hand the mic back (called before the main loop opens its own stream)."""
        t, evt = self._barge_thread, self._barge_stop
        self._barge_thread = None
        if evt is not None:
            evt.set()
        if t is not None and t.is_alive() and t is not threading.current_thread():
            t.join(timeout=1.0)
        self._duck.clear()

    def _load_stop_model(self):
        """A tiny English-only Whisper on the CPU, used only to recognise the
        spoken interrupt. Loaded in the background so startup isn't slower;
        until it's ready (or if it can't be downloaded) the main model is used."""
        if not (whisper_available and hasattr(self, "whisper_model") and self.barge_in_enabled):
            return

        def _go():
            try:
                self._stop_model = WhisperModel("tiny.en", device="cpu", compute_type="int8", cpu_threads=2)
            except Exception as e:
                print(f"[Barge-in] tiny.en unavailable ({e}); using the main model to hear 'stop'.")

        threading.Thread(target=_go, name="jupiter-stop-model", daemon=True).start()

    def _transcribe_stop_clip(self, audio) -> str:
        model = self._stop_model or getattr(self, "whisper_model", None)
        if model is None:
            return ""
        try:
            x = self._clean_audio(audio.reshape(-1, 1)).reshape(-1)
            x = np.ascontiguousarray(x, dtype=np.float32)
            segments, _ = model.transcribe(
                x, beam_size=1, language="en", temperature=0.0, without_timestamps=True,
                condition_on_previous_text=False, vad_filter=False,
            )
            return " ".join(s.text for s in segments).strip()
        except Exception as e:
            print(f"[Barge-in STT Error] {e}")
            return ""

    def _is_interrupt_phrase(self, text: str) -> bool:
        """True if the clip ENDS in an interrupt phrase ("... stop", "stop it",
        "okay jupiter stop")."""
        words = re.findall(r"[a-z']+", text.lower().replace("\u2019", "'"))
        for n in (1, 2, 3, 4):
            if len(words) >= n and INTERRUPT_PATTERN.match(" ".join(words[-n:])):
                return True
        return False

    def _barge_in_loop(self, stop_evt):
        """Runs only while Jupiter has something to say, and listens for you
        talking OVER the speakers:
          1. Jupiter's own voice leaks into the mic, so we measure how loud that
             leakage is (the loudest recent block) and only react to sound that
             is clearly louder - barge_in_ratio times louder.
          2. The moment that happens Jupiter pauses ("ducks"), which also keeps
             its voice out of the recording of yours.
          3. When you stop, the clip goes to a tiny CPU Whisper. If it ends in
             "stop" (see INTERRUPT_PATTERN) the speech is cut and the main loop
             starts listening; otherwise Jupiter just carries on where it was."""
        rate = self.sample_rate
        block = int(rate * 0.05)                      # 50 ms per read
        try:
            with _AUDIO_OPEN_LOCK:
                stream = sd.InputStream(samplerate=rate, channels=1, dtype="float32", blocksize=block)
                stream.start()
        except Exception as e:
            print(f"[Barge-in] couldn't open the mic ({e}); spoken interrupt is off.")
            self.barge_in_enabled = False
            return
        recent = []        # loudness of recent blocks while Jupiter talks = speaker leakage
        pre = []           # the last few blocks, so the clip includes the start of the word
        clip = None        # blocks of a possible interruption, once one starts
        loud = quiet = idle = false_alarms = 0
        ratio = self.barge_in_ratio
        max_ratio = self.barge_in_ratio * 2.5
        floor = self.barge_in_min_rms
        try:
            while not stop_evt.is_set() and self._barge_ready():
                data, _ = stream.read(block)
                x = data.reshape(-1)
                rms = float(np.sqrt(np.mean(x.astype(np.float64) ** 2)))

                if self._pending <= 0 or self._interrupted.is_set():
                    # Nothing to interrupt. Give up after a second of that; the
                    # next speak() starts a fresh monitor.
                    recent.clear()
                    pre.clear()
                    clip = None
                    loud = quiet = 0
                    self._duck.clear()
                    idle += 1
                    if idle >= 20:
                        stop_evt.set()          # mark as winding down so speak() can start a fresh monitor
                        return
                    continue
                idle = 0

                if clip is None:
                    pre.append(x)
                    del pre[:-6]
                    leak = max(recent) if recent else 0.0
                    floor = max(self.barge_in_min_rms, leak * ratio)
                    if self._playing.is_set() and len(recent) < 8:
                        recent.append(rms)            # first 0.4 s of speech: just learn the leakage level
                    elif rms > floor:
                        loud += 1
                        if loud >= 3:                 # ~150 ms of something louder than the leakage
                            clip = list(pre)
                            quiet = 0
                            self._duck.set()
                    else:
                        loud = 0
                        if self._playing.is_set():
                            recent.append(rms)
                            del recent[:-60]
                else:
                    clip.append(x)
                    quiet = 0 if rms > floor else quiet + 1
                    if quiet >= 6 or len(clip) >= 40:   # 300 ms of quiet, or a 2 s cap
                        heard = self._transcribe_stop_clip(np.concatenate(clip))
                        if heard and self._is_interrupt_phrase(heard):
                            print(f"[Interrupted] heard: {heard!r}")
                            self.interrupt_speech()
                            return
                        # Not "stop": carry on talking, and treat this loudness as
                        # speaker leakage so it doesn't trigger again.
                        recent.append(max(floor / ratio, 0.01) * 1.4)
                        del recent[:-60]
                        false_alarms += 1
                        clip = None
                        loud = quiet = 0
                        pre.clear()
                        self._duck.clear()
                        if false_alarms >= 4:
                            # Noisy room / loud speakers. The old code gave up
                            # here, which left "stop" dead for the rest of the
                            # reply. Stay on, just harder to trigger.
                            ratio = min(max_ratio, ratio * 1.4)
                            false_alarms = 0
        except Exception as e:
            print(f"[Barge-in Error] {e}")
        finally:
            stop_evt.set()
            self._duck.clear()
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass
