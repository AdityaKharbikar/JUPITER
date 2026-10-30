from ..common import *


class VocabularyMixin:
    def _load_vocabulary(self):
        """Load accepted/rejected words and build the 'already known' word set."""
        self.vocab_accepted = {}   # lowercase word -> display form
        self.vocab_rejected = set()
        try:
            for word, display, status in self.conn.execute(
                "SELECT word, display, status FROM vocabulary"
            ):
                if status == "accepted":
                    self.vocab_accepted[word] = display or word
                else:
                    self.vocab_rejected.add(word)
        except sqlite3.Error as e:
            print(f"[Vocabulary Load Error] {e}")

        self.known_words = set(BASE_LEXICON) | set(COMMAND_WORDS)
        self.known_words |= {k for key in APP_COMMANDS for k in key.split()}
        for song in self.favorite_songs:
            self.known_words |= {w.lower() for w in WORD_TOKEN_PATTERN.findall(song)}
        self.known_words |= set(self.vocab_accepted)

    def _build_vocab_hint(self) -> str:
        """Assemble Whisper's initial_prompt: fixed command words + favourite
        songs + the most-used learned words. Kept short on purpose — Whisper
        caps initial_prompt at ~224 tokens and a bloated prompt makes decoding
        worse, not better, so only the top learned words ride along.

        LANGUAGE-MATCHED to self.stt_language: initial_prompt is a biasing
        signal, not just a glossary, and mixing Hindi/Marathi phrases into a
        prompt used while decoding is forced to English can nudge Whisper
        toward code-switched or garbled phonetic guesses on short, ambiguous
        clips (e.g. a song title) — plausibly the exact mechanism behind
        outputs like "Lehaayon" for what was actually meant to be a normal
        English phrase. The Hindi/Marathi example words now only ride along
        when Jupiter is actually decoding in that language."""
        cache_key = (self.stt_language, self._vocab_version)
        cached = self._vocab_hint_cache
        if cached is not None and cached[0] == cache_key:
            return cached[1]
        with self._db_lock:
            learned = [
                display for (display,) in self.conn.execute(
                    "SELECT COALESCE(display, word) FROM vocabulary "
                    "WHERE status = 'accepted' ORDER BY hits DESC, added_at DESC LIMIT 40"
                )
            ]
        command_words = (
            "Play, open, search, weather, battery, volume, mute, unmute, "
            "YouTube, file explorer, text mode, voice mode, Jupiter, remind me, timer, "
            "stopwatch, note, news, translate, convert, calculate, conversation."
        )
        parts = [command_words]
        if self.stt_language in ("hi", "mr"):
            parts.append("Nagpur, Sitabuldi, Dharampeth, mausam, gaana, kaisa hai.")
        parts.append(", ".join(self.favorite_songs))
        if learned:
            parts.append(", ".join(learned))
        hint = ", ".join(p for p in parts if p)[:900]
        self._vocab_hint_cache = (cache_key, hint)
        return hint

    def _vocab_candidates(self, command: str) -> list:
        """Words in a command that Jupiter has never seen before, in order,
        deduplicated. Filters out short tokens, digits, anything already
        known/accepted/previously declined, AND anything in a real English
        dictionary (via pyspellchecker) — so ordinary words never get flagged
        just because they're missing from the small hand-typed BASE_LEXICON."""
        candidates = []
        seen = set()
        for token in WORD_TOKEN_PATTERN.findall(command):
            key = token.lower().strip("'-")
            if len(key) < 3 or not key.isalpha():
                continue
            if key in self.known_words or key in self.vocab_rejected or key in seen:
                continue
            if spellchecker_available and key in _spell:
                continue
            seen.add(key)
            candidates.append(token.strip("'-"))
        return candidates

    def maybe_learn_vocabulary(self, command: str):
        """Called only after a command was handled successfully. Offers to add
        up to two unfamiliar words per turn — more than that turns a single
        command into an interrogation."""
        if not self.vocab_learning or not command:
            return
        for word in self._vocab_candidates(command)[:2]:
            answer = self.ask_yes_no(
                f'"{word}" is new to me, {self.user_name}. '
                f'Shall I add it to my vocabulary?'
            )
            if answer is True:
                self.add_vocabulary_word(word)
            elif answer is False:
                self.reject_vocabulary_word(word)
            else:
                # Unclear answer — don't record anything, just move on. The word
                # stays a candidate, so it'll be offered again next time.
                self.speak("I'll leave it for now, sir.")

    def add_vocabulary_word(self, word: str, announce: bool = True):
        key = word.lower().strip("'-")
        if not key:
            return
        now = self._get_ist_time().isoformat()
        with self._db_lock:
            self.conn.execute(
                """
                INSERT INTO vocabulary (word, display, status, hits, added_at)
                VALUES (?, ?, 'accepted', 1, ?)
                ON CONFLICT(word) DO UPDATE SET
                    status = 'accepted', hits = hits + 1, display = excluded.display
                """,
                (key, word, now)
            )
            self.conn.commit()
        self.vocab_accepted[key] = word
        self.vocab_rejected.discard(key)
        self.known_words.add(key)
        self._vocab_version += 1
        if announce:
            self.speak(f"Added {word} to my vocabulary, sir.")

    def reject_vocabulary_word(self, word: str):
        key = word.lower().strip("'-")
        now = self._get_ist_time().isoformat()
        with self._db_lock:
            self.conn.execute(
                """
                INSERT INTO vocabulary (word, display, status, hits, added_at)
                VALUES (?, ?, 'rejected', 0, ?)
                ON CONFLICT(word) DO UPDATE SET status = 'rejected'
                """,
                (key, word, now)
            )
            self.conn.commit()
        self.vocab_rejected.add(key)
        self.vocab_accepted.pop(key, None)
        self._vocab_version += 1
        self.speak("Understood, sir. I won't ask about that one again.")

    def show_vocabulary(self):
        with self._db_lock:
            rows = self.conn.execute(
                "SELECT COALESCE(display, word), hits FROM vocabulary "
                "WHERE status = 'accepted' ORDER BY hits DESC, added_at DESC"
            ).fetchall()
        if not rows:
            self.speak("I haven't learned any new words yet, sir.")
            return
        words = ", ".join(f"{w}" for w, _ in rows)
        self.speak(f"I've learned {len(rows)} word(s), sir: {words}")

    def forget_vocabulary_word(self, word: str):
        key = word.lower().strip(" .!?'-")
        with self._db_lock:
            cursor = self.conn.execute("DELETE FROM vocabulary WHERE word = ?", (key,))
            self.conn.commit()
        if cursor.rowcount:
            self.vocab_accepted.pop(key, None)
            self.vocab_rejected.discard(key)
            self.known_words.discard(key)
            self._vocab_version += 1
            self.speak(f"Forgotten, sir. {word} is out of my vocabulary.")
        else:
            self.speak(f"I don't have {word} in my vocabulary, sir.")

    def ask_yes_no(self, question: str):
        """Ask a yes/no question using whichever input mode is active, so the
        prompt is answerable the same way the command was given. Returns True,
        False, or None if the answer wasn't a clear yes or no."""
        self._interrupted.clear()   # a fresh question is always worth speaking
        self.speak(question)
        reply = self.get_input("Answer (yes/no): ")
        if not reply:
            return None
        reply = reply.lower().strip()
        if YES_PATTERN.match(reply):
            return True
        if NO_PATTERN.match(reply):
            return False
        return None

    def get_input(self, prompt: str = "You: ") -> str:
        """One turn of input in the current mode. Used for confirmations, where
        we do NOT want the mode-switch escape hatches firing mid-question."""
        if self.input_mode == "text" or not self._voice_possible():
            return self._read_text_input(prompt)
        return self._listen_voice_input(keep_short=True)
