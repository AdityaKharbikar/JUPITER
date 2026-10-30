from ..common import *


class STTMixin:
    def transcribe(self, audio, quick: bool = False, keep_short: bool = False):
        """Speech -> text with Whisper. `audio` is 16 kHz mono float32 straight
        from the mic (a numpy array - no temp file, nothing written to disk, and
        no ffmpeg decode step), or a file path.

        GPU library errors only surface on the first real transcription call
        (not at model load) - if that happens, reload Whisper on CPU
        automatically and retry once, instead of failing every turn.

        Language is FORCED (self.stt_language), not auto-detected - auto-detection
        is unreliable on short, code-switched clips. initial_prompt nudges the
        vocabulary toward your commands and proper nouns. Decoding is greedy-
        deterministic (temperature 0, no timestamps): Whisper's default
        "retry at a higher temperature" fallback is what turns a short command
        into a *different* wrong answer on every attempt, and it costs extra
        decode passes.

        Also screens out likely hallucinations (Whisper writes fluent text from
        silence/noise): segments with a high no_speech_prob, or text that is
        exactly one of Whisper's stock phrases, are discarded. keep_short=True
        (used for yes/no confirmations) lets a bare "okay" through, because that
        is a legitimate answer there."""
        if not whisper_available or not hasattr(self, 'whisper_model'):
            return ""

        audio_input = audio
        if getattr(audio, "ndim", None) is not None:
            # faster-whisper insists on a 1-D float32 array ("Input should be a
            # 1D array" is what a (N, 1) mic buffer gets you).
            audio_input = np.ascontiguousarray(audio.reshape(-1), dtype=np.float32)

        # Rebuilt each call so words you approved earlier in this session are
        # already biasing the very next transcription - no restart needed.
        # quick=True is the cheap pass used on standby: English, wake-word prompt.
        vocab_hint = "Jupiter. Hey Jupiter. Wake up, Jupiter." if quick else self._build_vocab_hint()
        # CPU (int8) is meaningfully slower per beam than GPU (float16), so drop
        # to greedy decoding there; GPU keeps the more accurate beam search.
        beam_size = 2 if (not quick and getattr(self, 'whisper_device', 'cuda') == 'cuda') else 1
        language = "en" if quick else self.stt_language
        noise = self._WHISPER_NOISE_HALLUCINATIONS
        if keep_short:
            noise = noise - {"okay", "ok"}

        def _run_transcribe():
            try:
                # No vad_filter: the recorder already trimmed the clip to the
                # speech (+ a little padding), and a second VAD pass can clip a
                # soft first syllable ("play" -> "lay").
                return self.whisper_model.transcribe(
                    audio_input, beam_size=beam_size, language=language,
                    initial_prompt=vocab_hint, condition_on_previous_text=False,
                    temperature=0.0, without_timestamps=True, vad_filter=False, no_speech_threshold=0.75, compression_ratio_threshold=2.6,
                )
            except TypeError:
                # An older faster-whisper without one of those options.
                return self.whisper_model.transcribe(
                    audio_input, beam_size=beam_size, language=language,
                    initial_prompt=vocab_hint,
                )

        def _extract(segments):
            segments = list(segments)
            if not segments:
                return ""
            # Whisper reports, per segment, how likely it thinks the audio was
            # actually silence/non-speech. A real command scores low across the
            # board; noise hallucinations tend to run high.
            no_speech = [getattr(s, "no_speech_prob", 0.0) for s in segments]
            avg_no_speech = sum(no_speech) / len(no_speech)
            text = " ".join(s.text for s in segments).strip()
            if avg_no_speech > 0.6:
                return ""
            if text.lower().strip(" .!?") in noise:
                return ""
            return text

        try:
            segments, info = _run_transcribe()
            return _extract(segments)
        except Exception as e:
            print(f"[STT Error] {e}")
            if getattr(self, 'whisper_device', 'cuda') == 'cuda':
                print("GPU inference failed - reloading Whisper on CPU...")
                try:
                    self.whisper_model = WhisperModel(self.whisper_model_size, device="cpu", compute_type="int8", cpu_threads=self._cpu_threads())
                    self.whisper_device = "cpu"
                    beam_size = 1
                    print("Whisper ready (CPU).")
                    segments, info = _run_transcribe()
                    return _extract(segments)
                except Exception as e2:
                    print(f"[STT CPU Fallback Error] {e2}")
            return ""

    def set_stt_language(self, lang_name: str):
        """Switch what language Whisper decodes into. 'english' keeps command
        words reliable (song/place names get transliterated phonetically);
        'hindi'/'marathi' decode natively in that script for real conversation."""
        code = self.STT_LANGUAGES.get(lang_name.lower())
        if code:
            self.stt_language = code
            self.speak(f"Switched to {lang_name.capitalize()} mode, sir.")
        else:
            self.speak(f"I don't have a mode for {lang_name}, sir.")

    def _listen_voice_input(self, max_duration=None, quick: bool = False, keep_short: bool = False):
        """Record from the microphone until you stop speaking, then transcribe
        straight from memory (nothing is written to disk). Short commands finish
        fast, longer sentences aren't cut off at a mid-sentence pause. Falls back
        to text input if audio isn't available."""
        if not audio_input_available:
            return self._read_text_input("You: ")

        if not (whisper_available and hasattr(self, 'whisper_model')):
            return self._read_text_input("You (Whisper unavailable): ")

        # The "stop" listener owns the mic while Jupiter is talking; hand it
        # over before opening our own stream.
        self._stop_barge_monitor()

        chunk_duration = 0.1  # seconds analyzed per iteration
        chunk_samples = int(self.sample_rate * chunk_duration)
        speech_chunks_needed = max(1, int(self.min_speech_duration / chunk_duration))
        max_chunks = int((max_duration or self.max_listen_duration) / chunk_duration)

        chunks = []
        silence_run = 0
        speech_run = 0
        speech_started = False
        speech_start_idx = 0
        last_speech_idx = 0
        stream = None

        def _note(is_speech, idx):
            nonlocal silence_run, speech_run, speech_started, speech_start_idx, last_speech_idx
            if is_speech:
                speech_run += 1
                silence_run = 0
                last_speech_idx = idx
                if speech_run >= speech_chunks_needed and not speech_started:
                    speech_started = True
                    speech_start_idx = idx - speech_run + 1
            else:
                silence_run += 1
                speech_run = 0

        try:
            with _AUDIO_OPEN_LOCK:
                stream = sd.InputStream(samplerate=self.sample_rate, channels=1, dtype='float32')
                stream.start()

            # Briefly sample ambient noise and raise the effective threshold
            # above it if the room/mic is noisier than the fixed default
            # assumes. The audio is KEPT (not thrown away), and the quietest
            # chunk is used as the floor, so speech that starts inside this
            # window doesn't inflate it.
            calibration_chunks = max(1, int(0.4 / chunk_duration))
            ambient_levels = []
            for _ in range(calibration_chunks):
                data, _unused = stream.read(chunk_samples)
                chunks.append(data.copy())
                ambient_levels.append(float(np.sqrt(np.mean(data.astype(np.float64) ** 2))))
            ambient_rms = min(ambient_levels)
            effective_threshold = max(self.silence_threshold, ambient_rms * 3)
            heard_early = max(ambient_levels) > effective_threshold

            if not quick:
                print("Listening... (speak now)", flush=True)

            # Speech that began INSIDE the calibration window counts too - a
            # one-word command said right after the mic opens (e.g. straight
            # after "stop") used to be missed entirely.
            for i, level in enumerate(ambient_levels):
                _note(self._is_speech_chunk(chunks[:i + 1], level, effective_threshold, ambient_rms), i)

            for _ in range(max_chunks):
                data, _unused = stream.read(chunk_samples)
                chunks.append(data.copy())
                idx = len(chunks) - 1
                rms = float(np.sqrt(np.mean(data.astype(np.float64) ** 2)))
                _note(self._is_speech_chunk(chunks, rms, effective_threshold, ambient_rms), idx)

                # Stop once we've heard real speech followed by enough silence.
                # A longer sentence gets a longer grace period before we decide
                # you're done.
                if speech_started:
                    spoken = (last_speech_idx - speech_start_idx + 1) * chunk_duration
                    limit = self.silence_limit_long if spoken > 2.5 else self.silence_limit
                    if silence_run >= max(1, int(round(limit / chunk_duration))):
                        break

            stream.stop()
            stream.close()
            stream = None

            if not speech_started:
                if not quick:
                    print("No speech detected.")
                return ""

            # Trim to the speech plus a little padding. Whisper pads every clip to
            # 30 s anyway, so this isn't about speed - it's that long stretches of
            # silence are exactly what it hallucinates "Thank you." out of.
            first = 0 if heard_early else max(0, speech_start_idx - 4)
            last = min(len(chunks), last_speech_idx + 1 + 3)
            audio = np.concatenate(chunks[first:last], axis=0)
            if self.audio_cleanup:
                audio = self._clean_audio(audio)

            text = self.transcribe(audio, quick=quick, keep_short=keep_short)

            if text:
                print(f"You said: {text}")
                return text
            if not quick:
                print("No speech detected.")
            return ""

        except Exception as e:
            print(f"[Audio Error] {e}")
            return self._read_text_input("You (text fallback): ")

        finally:
            if stream is not None:
                try:
                    stream.stop()
                    stream.close()
                except Exception:
                    pass

    def _is_speech_chunk(self, chunks, rms, effective_threshold, ambient_rms) -> bool:
        """Is the audio that just arrived actual speech? Uses Silero VAD on the
        last ~0.6s and only counts it if speech is still going at the very end
        of that window, so a sentence that just finished isn't counted as
        speech for another half second. Falls back to the old loudness check
        if VAD isn't available or errors."""
        if not vad_available or getattr(self, "_vad_broken", False):
            return rms > effective_threshold
        # Cheap gate: clearly-quiet chunks are never speech, no model call.
        if rms < max(0.004, ambient_rms * 1.5):
            return False
        try:
            window = np.concatenate(chunks[-6:], axis=0).reshape(-1).astype(np.float32)
            opts = _FWVadOptions(
                threshold=self.vad_threshold,
                min_speech_duration_ms=100,
                min_silence_duration_ms=100,
                speech_pad_ms=0,
            )
            ts = _fw_speech_ts(window, opts)
            if not ts:
                return False
            return ts[-1]["end"] >= len(window) - int(0.12 * self.sample_rate)
        except Exception as e:
            print(f"[VAD Error] {e} - using loudness-based detection instead")
            self._vad_broken = True
            return rms > effective_threshold

    def _clean_audio(self, audio):
        """Mild clean-up before Whisper: cut rumble below ~80 Hz (fan, desk
        thumps) and lift a quiet recording to a healthy level. Deliberately
        NOT a heavy denoiser - Whisper is trained on noisy audio and
        aggressive filtering usually makes it worse."""
        try:
            x = audio.reshape(-1).astype(np.float32)
            if len(x) < 1600:
                return audio
            spec = np.fft.rfft(x)
            freqs = np.fft.rfftfreq(len(x), 1.0 / self.sample_rate)
            spec[freqs < 80] = 0
            x = np.fft.irfft(spec, n=len(x)).astype(np.float32)
            peak = float(np.max(np.abs(x)))
            if 0.003 < peak < 0.5:
                x *= min(0.7 / peak, 8.0)
            return np.clip(x, -1.0, 1.0).reshape(-1, 1)
        except Exception:
            return audio
