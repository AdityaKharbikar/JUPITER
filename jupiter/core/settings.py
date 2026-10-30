from ..common import *


class SettingsMixin:
    def _load_user_name(self):
        """Load a previously saved address term (e.g. 'sir', 'boss', a name), if any."""
        cursor = self.conn.execute(
            "SELECT value FROM metadata WHERE key = 'user_name'"
        )
        row = cursor.fetchone()
        if row and row[0]:
            self.user_name = row[0]

    def set_user_name(self, name: str):
        """Update and persist how JUPITER addresses the user."""
        name = name.strip()
        if not name:
            return
        self.user_name = name
        with self._db_lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
                ("user_name", name)
            )
            self.conn.commit()

    def _load_settings(self):
        """Restore input mode and vocabulary-learning preference from last run."""
        rows = dict(self.conn.execute(
            "SELECT key, value FROM metadata WHERE key IN "
            "('input_mode', 'vocab_learning', 'auto_return_to_voice', 'listen_mode')"
        ).fetchall())
        if rows.get("input_mode") in ("voice", "text"):
            self.input_mode = rows["input_mode"]
        if rows.get("vocab_learning") in ("0", "1"):
            self.vocab_learning = rows["vocab_learning"] == "1"
        if rows.get("auto_return_to_voice") in ("0", "1"):
            self.auto_return_to_voice = rows["auto_return_to_voice"] == "1"
        if rows.get("listen_mode") == LISTEN_PTT:
            self.listen_mode = LISTEN_PTT

    def _save_setting(self, key: str, value: str):
        with self._db_lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)", (key, value)
            )
            self.conn.commit()

    def set_input_mode(self, mode: str, announce: bool = True):
        """Switch between voice and text input, and remember the choice."""
        mode = mode.lower().strip()
        if mode not in ("voice", "text"):
            return
        if mode == "voice" and not self._voice_possible():
            self.speak("Voice input isn't available on this machine, sir. Staying in text mode.")
            self.input_mode = "text"
            self._save_setting("input_mode", "text")
            return
        self.input_mode = mode
        self._save_setting("input_mode", mode)
        if announce:
            if mode == "text":
                if self.auto_return_to_voice:
                    self.speak("Go ahead and type, sir. I'll be listening again right after.")
                else:
                    self.speak("Text mode, sir. Type your commands. Press Enter on an empty line to speak one instead.")
            else:
                self.speak("Voice mode, sir. I'm listening. Start typing at any time to switch to the keyboard.")

    def _voice_possible(self) -> bool:
        """True only if we can actually record AND transcribe."""
        return (
            audio_input_available
            and whisper_available
            and hasattr(self, "whisper_model")
        )
