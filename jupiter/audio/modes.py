from ..common import *


class AudioModesMixin:
    def listen_for_command(self):
        """Get one command in the current input mode.

        Typing is ONE-SHOT by default: whenever a turn comes from the keyboard,
        Jupiter flips straight back to the microphone for the next turn. So you
        type when you want to, speak the rest of the time, and never have to
        announce either. "stay in text mode" pins the keyboard open; "auto
        voice" restores the one-shot behaviour.

          voice mode -> just start typing. Jupiter notices keys in the buffer
                        before it opens the mic and takes that turn from the
                        keyboard instead. (Windows: any key. Linux/macOS: press
                        Enter, then type.)
          text mode  -> press Enter on an empty line to speak a single command
                        without leaving text mode.

        For a deliberate switch, say or type "text mode" / "voice mode" — both
        work in either mode, so a misheard STT language can never trap you.
        """
        # Typing or standby: nothing should be holding the mic open.
        if self.input_mode == "text" or self.listen_mode != LISTEN_ACTIVE:
            self._stop_barge_monitor()
        if self.listen_mode == LISTEN_SLEEP:
            return self._listen_while_sleeping()
        if self.listen_mode == LISTEN_PTT and self.input_mode != "text" and self._voice_possible():
            return self._listen_push_to_talk()
        if self.input_mode == "text" or not self._voice_possible():
            label = "You (text): " if self._voice_possible() else "You: "
            typed = self._read_text_input(label)
            if typed == "" and self._voice_possible():
                # Empty Enter = "let me say this one out loud", without
                # disturbing whichever mode you're pinned in.
                return self._listen_voice_input()
            if typed and self.auto_return_to_voice and self._voice_possible():
                # One-shot: this typed turn is done, next one is spoken.
                self._revert_to_voice()
            return typed

        pending = self._pending_keyboard_input()
        if pending is not None:
            text, complete = pending
            if not complete:
                try:
                    text += input("")
                except (EOFError, KeyboardInterrupt):
                    pass
            # Already in voice mode, so this was inherently a one-shot — the
            # next turn goes back to the mic with no bookkeeping needed.
            return text.strip()

        return self._listen_voice_input()

    def set_listen_mode(self, mode: str, announce: bool = True):
        """Switch between always-listening and push-to-talk. Remembered
        across restarts. (Sleep has its own method and is never persisted.)"""
        if mode == LISTEN_PTT and not self._voice_possible():
            self.speak(f"Push to talk needs the microphone, {self.user_name}, and voice input isn't available here.")
            return
        self.listen_mode = mode
        self._save_setting("listen_mode", mode)
        if mode == LISTEN_PTT and self.input_mode == "text":
            # Push-to-talk is a voice mode; leave a pinned text mode behind.
            self.input_mode = "voice"
            self._save_setting("input_mode", "voice")
        if announce:
            self.speak(self._pick(PTT_ENTER if mode == LISTEN_PTT else ACTIVE_ENTER))

    def enter_sleep_mode(self):
        """Standby: Jupiter stays running (timers and reminders still fire) but
        ignores everything until a wake phrase."""
        self._mode_before_sleep = self.listen_mode if self.listen_mode != LISTEN_SLEEP else LISTEN_ACTIVE
        self.speak(self._pick(SLEEP_ENTER))
        self.listen_mode = LISTEN_SLEEP

    def wake_from_sleep(self, greet: bool = True):
        self.listen_mode = self._mode_before_sleep or LISTEN_ACTIVE
        if greet:
            self.speak(self._pick(WAKE_FROM_SLEEP))

    def _split_wake(self, text: str, sleeping: bool = False):
        """Look for a wake phrase. Returns (woke, remainder):
          "hey jupiter"                  -> (True, "")
          "hey jupiter what's the time"  -> (True, "what's the time")
          "what's the time, jupiter"     -> (True, "what's the time")
          "Jupiter has how many moons"   -> (False, <unchanged>)  [while active]
        While sleeping, nameless phrases like "wake up" also count, and any
        sentence that starts with the name wakes Jupiter."""
        t = text.strip()
        if WAKE_ONLY_PATTERN.match(t):
            return True, ""
        if sleeping and WAKE_NONAME_PATTERN.match(t):
            return True, ""
        m = WAKE_PREFIX_PATTERN.match(t)
        if m:
            rest = t[m.end():].strip()
            first = rest.split(None, 1)[0].lower().strip(".,!?") if rest else ""
            strong = bool(m.group("lead")) or bool(m.group("punct")) or first in WAKE_COMMAND_VERBS
            if rest and strong:
                return True, rest
            if sleeping:
                return True, t
            return False, text
        tm = WAKE_TRAILING_PATTERN.search(t)
        if tm and t[:tm.start()].strip():
            return True, t[:tm.start()].strip()
        return False, text

    def _listen_while_sleeping(self) -> str:
        """One poll of the standby loop. Returns text ONLY if it contains a
        wake phrase; everything else is dropped on the floor. Uses a short,
        cheap transcription so standby stays light on CPU/GPU."""
        heard = ""
        if self.input_mode == "text" or not self._voice_possible():
            heard = self._read_text_input("(standby) You: ")
        else:
            pending = self._pending_keyboard_input()
            if pending is not None:
                text, complete = pending
                if not complete:
                    try:
                        text += input("")
                    except (EOFError, KeyboardInterrupt):
                        pass
                heard = text.strip()
            else:
                heard = self._listen_voice_input(max_duration=8, quick=True)
        if not heard:
            return ""
        woke, _ = self._split_wake(heard, sleeping=True)
        if woke:
            return heard
        print(f"[standby] ignored: {heard}")
        return ""

    def _poll_ptt_key(self):
        """Non-blocking keyboard check for push-to-talk. Returns None (nothing
        pressed), ("ptt", "") for Enter/Space, or ("text", line) if the user
        started typing a command instead."""
        try:
            if sys.platform == "win32":
                import msvcrt
                if not msvcrt.kbhit():
                    return None
                ch = msvcrt.getwch()
                if ch in ("\r", "\n", " "):
                    return ("ptt", "")
                if ch == "\x03":
                    raise KeyboardInterrupt
                if ch in ("\x00", "\xe0"):      # arrow / function key prefix
                    msvcrt.getwch()
                    return None
                print(f"You (typed): {ch}", end="", flush=True)
                try:
                    rest = input("")
                except (EOFError, KeyboardInterrupt):
                    rest = ""
                return ("text", (ch + rest).strip())
            import select
            if select.select([sys.stdin], [], [], 0)[0]:
                line = sys.stdin.readline().rstrip("\n").strip()
                return ("text", line) if line else ("ptt", "")
            return None
        except KeyboardInterrupt:
            raise
        except Exception:
            return None

    def _listen_push_to_talk(self) -> str:
        """Wait for Enter/Space, then record ONE utterance. Typing a command
        and pressing Enter also works. The mic stays closed until you press a
        key, and reminders/timers are still announced while waiting."""
        print("[Push to talk] Press Enter or Space, then speak (or type a command).", flush=True)
        while self.is_running:
            self.drain_events()
            key = self._poll_ptt_key()
            if key is None:
                time.sleep(0.05)
                continue
            kind, text = key
            if kind == "text":
                return text
            return self._listen_voice_input()
        return ""

    def _revert_to_voice(self):
        """Silently return to voice input after a one-shot typed command. No
        announcement — the whole point is that switching costs you nothing."""
        self.input_mode = "voice"
        self._save_setting("input_mode", "voice")
