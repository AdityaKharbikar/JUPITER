from ..common import *


class NotesClipboardService:
    def _read_text_input(self, prompt: str = "You: ") -> str:
        """Blocking keyboard read. Returns '' on EOF/interrupt rather than raising."""
        try:
            return input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            return ""

    def _pending_keyboard_input(self):
        """Non-blocking check for 'the user has started typing'.

        Returns None if the keyboard is idle, otherwise (text, is_complete):
          - Windows: characters already buffered, is_complete False — we echo
            them and let input() collect the rest of the line.
          - POSIX: the terminal is line-buffered, so anything available is a
            whole line already (press Enter to grab the turn), is_complete True.
        """
        try:
            if sys.platform == "win32":
                import msvcrt
                if not msvcrt.kbhit():
                    return None
                buf = ""
                first = True
                while msvcrt.kbhit():
                    ch = msvcrt.getwch()
                    if ch in ("\r", "\n"):
                        print()  # move off the echoed line before returning
                        return (buf, True)
                    if ch == "\x08":       # backspace
                        if buf:
                            buf = buf[:-1]
                            # Visually erase the character we just removed:
                            # move back, overwrite with a space, move back again.
                            print("\b \b", end="", flush=True)
                        continue
                    if ch == "\x03":       # Ctrl-C
                        raise KeyboardInterrupt
                    buf += ch
                    # getwch() reads the keystroke WITHOUT echoing it to the
                    # console (that's what getwche() is for) — the previous
                    # version only printed the whole buffered batch once,
                    # after this loop drained it, so anything typed was
                    # invisible until Jupiter happened to catch up. Echoing
                    # each character here, as it's consumed, is what actually
                    # shows you what you're typing.
                    if first:
                        print("You (typed): ", end="", flush=True)
                        first = False
                    print(ch, end="", flush=True)
                return (buf, False)
            else:
                import select
                if select.select([sys.stdin], [], [], 0)[0]:
                    return (sys.stdin.readline().rstrip("\n"), True)
                return None
        except KeyboardInterrupt:
            raise
        except Exception:
            return None

    def _clipboard_text(self):
        if not pyperclip_available:
            self.speak(f"Clipboard access needs pyperclip, {self.user_name}. Run: pip install pyperclip")
            return None
        try:
            text = pyperclip.paste()
        except Exception as e:
            print(f"[Clipboard Error] {e}")
            self.speak(f"I couldn't read the clipboard, {self.user_name}.")
            return None
        if not text or not text.strip():
            self.speak(f"The clipboard is empty, {self.user_name}.")
            return None
        return text.strip()

    def read_clipboard(self, limit: int = 600):
        text = self._clipboard_text()
        if text is None:
            return
        if len(text) > limit:
            self.speak(f"The clipboard holds {len(text)} characters, {self.user_name}. The first part reads:")
            self.speak(text[:limit] + "...")
        else:
            self.speak(text)

    def summarise_clipboard(self):
        text = self._clipboard_text()
        if text is None:
            return
        # Keep the prompt bounded so a huge paste can't stall the local model
        excerpt = text[:6000]
        self.speak(f"Summarising {len(text)} characters, {self.user_name}. One moment.")
        summary = self._call_summary_api(excerpt)
        if summary:
            self.speak(summary)
        else:
            self.speak(f"I couldn't summarise that, {self.user_name}. Is Ollama running?")

    def copy_last_response(self):
        """Write Jupiter's last spoken line to the clipboard."""
        if not pyperclip_available:
            self.speak(f"Copying needs pyperclip, {self.user_name}. Run: pip install pyperclip")
            return
        last = getattr(self, "_previous_response", "") or getattr(self, "_last_response", "")
        if not last:
            self.speak(f"I haven't said anything worth copying yet, {self.user_name}.")
            return
        try:
            pyperclip.copy(last)
            self.speak(f"Copied to your clipboard, {self.user_name}.")
        except Exception as e:
            print(f"[Clipboard Error] {e}")
            self.speak(f"I couldn't write to the clipboard, {self.user_name}.")

    def _notes_path(self) -> str:
        return os.path.join(self.data_dir, "notes.md")

    def add_note(self, text: str):
        text = text.strip().rstrip(".")
        if not text:
            self.speak(f"What should I note down, {self.user_name}?")
            return
        try:
            stamp = self._get_ist_time().strftime("%Y-%m-%d %H:%M")
            with open(self._notes_path(), "a", encoding="utf-8") as f:
                f.write(f"- [{stamp}] {text}\n")
            self.speak(f"Noted, {self.user_name}.")
        except OSError as e:
            print(f"[Notes Error] {e}")
            self.speak(f"I couldn't write that note, {self.user_name}.")

    def read_notes(self, count: int = 10):
        path = self._notes_path()
        if not os.path.exists(path):
            self.speak(f"You haven't saved any notes yet, {self.user_name}.")
            return
        try:
            with open(path, encoding="utf-8") as f:
                lines = [l.strip() for l in f if l.strip()]
        except OSError as e:
            print(f"[Notes Error] {e}")
            self.speak(f"I couldn't read your notes, {self.user_name}.")
            return
        if not lines:
            self.speak(f"Your notes file is empty, {self.user_name}.")
            return
        recent = lines[-count:]
        self.speak(f"Your {len(recent)} most recent note(s), {self.user_name}:")
        for line in recent:
            # Strip the "- [timestamp] " prefix when speaking it back
            self.speak(re.sub(r'^-\s*\[[^\]]*\]\s*', '', line))

    def clear_notes(self):
        """Archive rather than delete. The old notes are renamed with a
        timestamp so nothing is ever actually destroyed by a voice command."""
        path = self._notes_path()
        if not os.path.exists(path):
            self.speak(f"There are no notes to clear, {self.user_name}.")
            return
        confirmed = self.ask_yes_no(f"Archive all your notes, {self.user_name}?")
        if confirmed is not True:
            self.speak(f"Leaving your notes alone, {self.user_name}.")
            return
        try:
            stamp = self._get_ist_time().strftime("%Y%m%d-%H%M%S")
            archive = os.path.join(self.data_dir, f"notes-{stamp}.md")
            os.rename(path, archive)
            self.speak(f"Notes archived, {self.user_name}. The old file is still in your data folder.")
        except OSError as e:
            print(f"[Notes Error] {e}")
            self.speak(f"I couldn't archive your notes, {self.user_name}.")
