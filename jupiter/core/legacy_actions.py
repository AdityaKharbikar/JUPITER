from ..common import *


class LegacyActionsMixin:
    def _normalise_command(self, text: str) -> str:
        """The command patterns are anchored (^play, ^open, whole-phrase time/date),
        so one filler word or a polite wrapper used to send a perfectly good
        command to the LLM, which then improvised. This strips fillers and
        politeness ("um, could you please open notepad for me" -> "open
        notepad"), turns spoken numbers into digits for volume ("set volume to
        fifty"), and turns spoken arithmetic into a calculate command ("what is
        twelve times five"). The LLM still receives your original words - this
        only feeds the command matcher."""
        original = text.strip()
        t = FILLER_LEAD_PATTERN.sub("", original)
        t = POLITE_LEAD_PATTERN.sub("", t)
        stripped = POLITE_TAIL_PATTERN.sub("", t).strip()
        # "play thank you" is a song, not "play" + politeness
        if stripped and stripped.lower().split()[-1] not in self._NEEDS_ARGUMENT:
            t = stripped
        t = t.strip()
        if not t:
            return original
        if re.search(r"\bvolume\b", t, re.IGNORECASE):
            return self._spoken_numbers_to_digits(t)
        m = SPOKEN_MATH_PATTERN.match(t)
        if m:
            expr = self._spoken_math_expression(m.group(1))
            if expr:
                return f"calculate {expr}"
        return t

    def _spoken_numbers_to_digits(self, text: str) -> str:
        """'seventy five' -> '75', 'a hundred' -> '100'. 0-999 is plenty here."""
        units, tens = self._NUM_UNITS, self._NUM_TENS
        text = re.sub(r"\ba\s+hundred\b", "hundred", text, flags=re.IGNORECASE)
        tokens = text.split()

        def word(k):
            return tokens[k].lower().strip(".,!?")

        out = []
        i = 0
        while i < len(tokens):
            if word(i) in units or word(i) in tens or word(i) == "hundred":
                total = 0
                j = i
                while j < len(tokens):
                    w = word(j)
                    if w in units:
                        total += units[w]
                    elif w in tens:
                        total += tens[w]
                    elif w == "hundred":
                        total = max(total, 1) * 100
                    else:
                        break
                    j += 1
                out.append(str(total))
                i = j
            else:
                out.append(tokens[i])
                i += 1
        return " ".join(out)

    def _spoken_math_expression(self, spoken: str):
        """'twelve times five' -> '12 * 5'. None unless it is pure arithmetic."""
        s = self._spoken_numbers_to_digits(spoken.lower())
        for pattern, symbol in (
            (r"\bto the power of\b", " ** "),
            (r"\bmultiplied by\b|\btimes\b|\bx\b", " * "),
            (r"\bdivided by\b|\bover\b", " / "),
            (r"\bplus\b", " + "),
            (r"\bminus\b", " - "),
        ):
            s = re.sub(pattern, symbol, s)
        s = re.sub(r"\s+", " ", s).strip()
        if re.fullmatch(r"[\d\s+\-*/().%]+", s) and re.search(r"\d", s) and re.search(r"[+\-*/%]", s):
            return s
        return None

    def handle_action(self, command):
        """Execute practical tasks — returns True if handled"""
        cmd = command.lower().strip()
        # Set by meta-commands (mode switching, vocabulary management) so the
        # main loop doesn't offer to learn words from a command about words.
        self._skip_vocab = False

        # ----- Listening modes: sleep / push-to-talk / always listening ----
        # Anchored full-phrase patterns, so "how much sleep do I need" is
        # still a normal question. Checked first so nothing can swallow them.
        if SLEEP_MODE_PATTERN.match(cmd):
            self._skip_vocab = True
            self.enter_sleep_mode()
            return True
        if PTT_MODE_PATTERN.match(cmd):
            self._skip_vocab = True
            self.set_listen_mode(LISTEN_PTT)
            return True
        if ACTIVE_MODE_PATTERN.match(cmd):
            self._skip_vocab = True
            self.set_listen_mode(LISTEN_ACTIVE)
            return True

        # ----- Long-term memory and conversation recall --------------------
        fact_match = REMEMBER_FACT_PATTERN.match(command)
        if fact_match:
            self._skip_vocab = True
            self.remember_fact(fact_match.group(1))
            return True
        if RECALL_FACTS_PATTERN.search(cmd):
            self._skip_vocab = True
            self.recall_facts()
            return True
        if FORGET_FACTS_PATTERN.search(cmd):
            self._skip_vocab = True
            self.forget_facts()
            return True
        if WHAT_DISCUSSED_PATTERN.search(cmd):
            self._skip_vocab = True
            self.recall_discussion(cmd)
            return True

        # Time/Date (IST). The sun/moon guard matters because "what time is
        # sunrise" contains "time" and would otherwise just get the clock.
        if TIME_PATTERN.search(cmd) and not (SUN_PATTERN.search(cmd) or MOON_PATTERN.search(cmd)):
            now = self._get_ist_time()
            self.speak(f"It is {now.strftime('%I:%M %p')}, {self.user_name}.")
            return True

        if DATE_PATTERN.search(cmd):
            now = self._get_ist_time()
            self.speak(f"Today is {now.strftime('%A, %B %d, %Y')}, sir.")
            return True

        # Weather (defaults to Nagpur if no place given)
        weather_match = WEATHER_PATTERN.search(cmd)
        if weather_match:
            self.get_weather(weather_match.group(1))
            return True

        # Battery status
        if BATTERY_PATTERN.search(cmd):
            self.get_battery_status()
            return True

        # Volume control
        volume_set_match = VOLUME_SET_PATTERN.search(cmd)
        if volume_set_match:
            self.set_volume(level=int(volume_set_match.group(1)))
            return True
        if VOLUME_UP_PATTERN.search(cmd):
            self.set_volume(direction="up")
            return True
        if VOLUME_DOWN_PATTERN.search(cmd):
            self.set_volume(direction="down")
            return True
        if VOLUME_MUTE_PATTERN.match(cmd):
            self.set_volume(direction="mute")
            return True
        if VOLUME_UNMUTE_PATTERN.match(cmd):
            self.set_volume(direction="unmute")
            return True

        # ----- Timers and stopwatch ----------------------------------------
        # Before TIME_PATTERN would be wrong (it's earlier in this method), but
        # TIME_PATTERN uses \btime\b so "timer" never triggers it.
        timer_set = TIMER_SET_PATTERN.search(cmd)
        if timer_set:
            self._skip_vocab = True
            self.set_timer(timer_set.group(1))
            return True

        if TIMER_LIST_PATTERN.search(cmd):
            self._skip_vocab = True
            self.list_timers()
            return True

        if TIMER_CANCEL_PATTERN.search(cmd):
            self._skip_vocab = True
            self.cancel_timers()
            return True

        if STOPWATCH_START_PATTERN.search(cmd):
            self._skip_vocab = True
            self.start_stopwatch()
            return True

        if STOPWATCH_READ_PATTERN.search(cmd):
            self._skip_vocab = True
            self.read_stopwatch(stop=cmd.strip().startswith("stop"))
            return True

        # ----- Clipboard ----------------------------------------------------
        # Summarise is checked first: "summarise my clipboard" also matches the
        # plain read pattern's verb set in some phrasings.
        if CLIPBOARD_SUMMARISE_PATTERN.search(cmd):
            self._skip_vocab = True
            self.summarise_clipboard()
            return True

        if CLIPBOARD_READ_PATTERN.search(cmd):
            self._skip_vocab = True
            self.read_clipboard()
            return True

        if CLIPBOARD_COPY_PATTERN.search(cmd):
            self._skip_vocab = True
            self.copy_last_response()
            return True

        # ----- System / network --------------------------------------------
        if SYSTEM_STATS_PATTERN.search(cmd):
            self._skip_vocab = True
            self.get_system_stats()
            return True

        if WIFI_PATTERN.search(cmd):
            self._skip_vocab = True
            self.get_network_info()
            return True

        # ----- Conversion ---------------------------------------------------
        convert_match = CONVERT_PATTERN.search(cmd)
        if convert_match:
            self._skip_vocab = True
            self.convert_units(*convert_match.groups())
            return True

        # ----- Local documents ---------------------------------------------
        # Checked before the generic web search, or "search my documents for X"
        # would be sent to DuckDuckGo.
        doc_index_match = DOC_INDEX_PATTERN.search(cmd)
        if doc_index_match:
            self._skip_vocab = True
            self.index_documents(doc_index_match.group(1))
            return True

        if DOC_STATUS_PATTERN.search(cmd):
            self._skip_vocab = True
            self.document_status()
            return True

        doc_ask_match = DOC_ASK_PATTERN.search(command.strip())
        if doc_ask_match:
            self._skip_vocab = True
            self.ask_documents(doc_ask_match.group(1) or doc_ask_match.group(2) or "")
            return True

        # ----- Notes --------------------------------------------------------
        # Clear before read before add, so "clear my notes" isn't swallowed.
        if NOTE_CLEAR_PATTERN.search(cmd):
            self._skip_vocab = True
            self.clear_notes()
            return True

        if NOTE_READ_PATTERN.search(cmd):
            self._skip_vocab = True
            self.read_notes()
            return True

        note_add_match = NOTE_ADD_PATTERN.search(command.strip())
        if note_add_match:
            self.add_note(note_add_match.group(1))
            return True

        # ----- Sky ----------------------------------------------------------
        sun_match = SUN_PATTERN.search(cmd)
        if sun_match:
            self._skip_vocab = True
            self.get_sun_times(sun_match.group(1), sun_match.group(2))
            return True

        if MOON_PATTERN.search(cmd):
            self._skip_vocab = True
            self.get_moon_phase()
            return True

        # ----- News ---------------------------------------------------------
        news_match = NEWS_PATTERN.search(cmd)
        if news_match:
            self._skip_vocab = True
            self.get_news(news_match.group(1))
            return True

        # ----- Usage history ------------------------------------------------
        if HISTORY_STATS_PATTERN.search(cmd):
            self._skip_vocab = True
            self.show_usage_stats()
            return True

        # ----- Input mode (voice <-> text) ---------------------------------
        # Checked BEFORE the language-mode patterns so "text mode" is never
        # read as a language switch. These also set _skip_vocab so Jupiter
        # doesn't turn around and offer to learn its own control words.
        # Pin the keyboard open / restore one-shot typing. Must come before
        # TEXT_MODE_PATTERN, which "stay in text mode" also matches.
        if STICKY_TEXT_PATTERN.search(cmd):
            self._skip_vocab = True
            self.auto_return_to_voice = False
            self._save_setting("auto_return_to_voice", "0")
            self.set_input_mode("text", announce=False)
            self.speak("Staying in text mode, sir. Say auto voice when you want the mic back by default.")
            return True

        if AUTO_VOICE_PATTERN.search(cmd):
            self._skip_vocab = True
            self.auto_return_to_voice = True
            self._save_setting("auto_return_to_voice", "1")
            self.set_input_mode("voice", announce=False)
            self.speak("Back to voice, sir. Typed commands will be one-offs from now on.")
            return True

        if TEXT_MODE_PATTERN.search(cmd):
            self._skip_vocab = True
            self.set_input_mode("text")
            return True

        if VOICE_MODE_PATTERN.search(cmd):
            self._skip_vocab = True
            self.set_input_mode("voice")
            return True

        if WHICH_MODE_PATTERN.search(cmd):
            self._skip_vocab = True
            lang = next(
                (k for k, v in self.STT_LANGUAGES.items() if v == self.stt_language),
                self.stt_language
            )
            pin = "" if self.auto_return_to_voice else " Typing is pinned open."
            listen = {"active": "always listening", "push_to_talk": "push to talk",
                      "sleep": "standby"}.get(self.listen_mode, self.listen_mode)
            self.speak(f"{self.input_mode.capitalize()} input, {lang} speech, {listen}, sir.{pin}")
            return True

        # ----- Vocabulary management ---------------------------------------
        forget_match = VOCAB_FORGET_PATTERN.search(cmd)
        if forget_match:
            self._skip_vocab = True
            self.forget_vocabulary_word(forget_match.group(1))
            return True

        if VOCAB_SHOW_PATTERN.search(cmd):
            self._skip_vocab = True
            self.show_vocabulary()
            return True

        if VOCAB_ON_PATTERN.search(cmd):
            self._skip_vocab = True
            self.vocab_learning = True
            self._save_setting("vocab_learning", "1")
            self.speak("Vocabulary learning is on, sir. I'll ask before adding anything.")
            return True

        if VOCAB_OFF_PATTERN.search(cmd):
            self._skip_vocab = True
            self.vocab_learning = False
            self._save_setting("vocab_learning", "0")
            self.speak("Vocabulary learning is off, sir.")
            return True

        # Proactively teach a word/phrase (e.g. "remember the word Harry Potter")
        # instead of waiting for the auto-learn loop, which can't bootstrap on a
        # word Whisper has never once transcribed correctly to begin with.
        teach_match = TEACH_WORD_PATTERN.search(command)
        if teach_match:
            self._skip_vocab = True
            phrase = next(g for g in teach_match.groups() if g is not None).strip().rstrip(".!?")
            if phrase:
                self.add_vocabulary_word(phrase)
            return True

        # Switch STT language mode (english/hindi/marathi)
        lang_match = LANG_MODE_PATTERN.search(cmd)
        if lang_match:
            lang_name = lang_match.group(1) or lang_match.group(2)
            self.set_stt_language(lang_name)
            return True

        # Set how JUPITER addresses the user (persists across sessions)
        call_me_match = CALL_ME_PATTERN.search(cmd)
        if call_me_match:
            new_name = call_me_match.group(1).strip().rstrip(".!?")
            self.set_user_name(new_name)
            self.speak(f"Understood, {self.user_name}. I'll call you that from now on.")
            return True

        # Identity
        if IDENTITY_PATTERN.search(cmd):
            self.speak("I am JUPITER, your personal AI assistant, sir. Running entirely on this laptop.")
            return True

        # Calculation
        if CALCULATE_WORD_PATTERN.search(cmd) or CALCULATE_EXPR_PATTERN.match(cmd):
            try:
                expr = CALCULATE_WORD_PATTERN.sub("", cmd).replace("=", "").strip()
                # AST-whitelist evaluator — unlike eval(), this cannot execute
                # arbitrary Python even in principle: only numbers, +-*/%**,
                # unary +/-, and a small whitelist of math functions parse at all.
                result = self._safe_eval_math(expr)
                self.speak(f"The answer is {result}")
                return True
            except Exception:
                # Not a valid expression after all — fall through so other
                # patterns (or the LLM) get a chance at this command instead.
                pass

        # Search YouTube specifically (must be checked before generic Web Search
        # below, or "search X on youtube" would be sent to DuckDuckGo instead)
        youtube_search_match = YOUTUBE_SEARCH_PATTERN.search(cmd)
        if youtube_search_match and youtube_query(youtube_search_match):
            self.open_youtube(youtube_query(youtube_search_match))
            return True

        # Location / directions must be checked before generic Web Search.
        # SEARCH_PATTERN also matches "find", so otherwise "find location of X"
        # would be treated as a web search.
        location_match = LOCATION_PATTERN.search(cmd)
        if location_match:
            self.find_location(location_match.group(1).strip())
            return True

        # Web Search
        search_match = SEARCH_PATTERN.search(cmd)
        if search_match:
            query = search_match.group(1).strip()
            if query:
                url = f"https://duckduckgo.com/html/?q={query.replace(' ', '+')}"
                webbrowser.open(url)  # already imported at module level
                self.speak(f"Searching for {query} on the web, sir.")
                return True

        # Translation
        if TRANSLATE_TRIGGER_PATTERN.search(cmd):
            # "translate hello to spanish"
            match = TRANSLATE_PARSE_PATTERN.search(cmd)
            if match:
                text, lang = match.groups()
                result = self.translate_text(text.strip(), lang)
                self.speak(f"In {lang}, that is: {result}")
                return True
            else:
                self.speak("Please say: translate [phrase] to [language]")
                return True

        # ----- Conversation Management -------------------------------------
        if NEW_CONV_WITH_SUMMARY_PATTERN.search(cmd):
            outgoing_conv_id = self.current_conv_id

            # Reuse an existing summary of the conversation we're leaving if one
            # exists (e.g. from an earlier "summarise"), otherwise generate one now.
            carried_summary = self._get_conversation_summary()
            if not carried_summary:
                outgoing_text = self._fetch_conversation_text(outgoing_conv_id)
                if outgoing_text:
                    carried_summary = self._call_summary_api(outgoing_text)

            initial_summary = (
                f"Carried over from a previous conversation: {carried_summary}"
                if carried_summary else None
            )

            now = self._get_ist_time().isoformat()
            with self._db_lock:
                if carried_summary:
                    self.conn.execute(
                        "UPDATE conversation_threads SET summary = ? WHERE conv_id = ?",
                        (carried_summary, outgoing_conv_id)
                    )
                cursor = self.conn.execute(
                    "INSERT INTO conversation_threads (created_at, summary) VALUES (?, ?)",
                    (now, initial_summary)
                )
                new_id = cursor.lastrowid
                self.current_conv_id = new_id
                self.conn.execute(
                    "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
                    ("last_conv_id", str(new_id))
                )
                self.conn.commit()
            if carried_summary:
                self.speak(f"Started new conversation #{new_id} with prior context carried over, {self.user_name}.")
            else:
                self.speak(f"Started new conversation #{new_id}, {self.user_name}. Nothing to carry over yet.")
            return True

        if NEW_CONV_PATTERN.search(cmd):
            now = self._get_ist_time().isoformat()
            with self._db_lock:
                cursor = self.conn.execute(
                    "INSERT INTO conversation_threads (created_at, summary) VALUES (?, ?)",
                    (now, None)
                )
                new_id = cursor.lastrowid
                self.current_conv_id = new_id
                self.conn.execute(
                    "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
                    ("last_conv_id", str(new_id))
                )
                self.conn.commit()
            self.speak(f"Started new conversation #{new_id}, {self.user_name}.")
            return True

        switch_match = SWITCH_CONV_PATTERN.search(cmd)
        if switch_match:
            self.set_current_conversation(int(switch_match.group(1)))
            return True
        if "switch" in cmd and "conversation" in cmd:
            # Had both keywords but no number — original fallback message
            self.speak("Usage: switch conversation <id>, sir.")
            return True

        if LIST_CONV_PATTERN.search(cmd):
            self.list_conversations()
            return True

        if CONTINUE_PATTERN.match(cmd):
            summary = self._get_conversation_summary()
            if summary:
                self.speak(f"Continuing conversation #{self.current_conv_id}, sir. Previous: {summary[:80]}...")
            else:
                self.speak(f"Continuing conversation #{self.current_conv_id}, sir.")
            return True

        # Summarise command
        if SUMMARISE_PATTERN.search(cmd):
            self.summarise_conversation()
            return True

        # Reminders
        remind_match = REMIND_PATTERN.search(cmd)
        if remind_match:
            task = remind_match.group(1).strip()
            self.add_reminder(task)
            return True

        # "remind me in 20 minutes to call Mom" — duration before the task.
        # Reorder to "call Mom in 20 minutes" so _parse_when's existing
        # "<task> in <duration>" logic picks up both correctly.
        remind_in_match = REMIND_IN_PATTERN.search(cmd)
        if remind_in_match:
            when_clause, task = remind_in_match.groups()
            self.add_reminder(f"{task.strip()} {when_clause.strip()}")
            return True

        if SHOW_REMINDERS_PATTERN.search(cmd):
            self.list_reminders()
            return True

        if CLEAR_REMINDERS_PATTERN.search(cmd):
            self.clear_reminders()
            return True

        # Open File
        open_file_match = OPEN_FILE_PATTERN.match(cmd)
        if open_file_match:
            path = open_file_match.group(1).strip()
            if os.path.exists(path):
                os.startfile(path)
                self.speak(f"Opening {path}, sir.")
            else:
                self.speak("File not found, sir.")
            return True

        # Open File Explorer
        if EXPLORER_PATTERN.match(cmd):
            self.open_file_explorer()
            return True

        # Open YouTube (no search term)
        if YOUTUBE_OPEN_PATTERN.match(cmd):
            self.open_youtube()
            return True

        # Play a song / media
        play_match = PLAY_PATTERN.match(cmd)
        if play_match:
            self.play_song(play_match.group(1).strip())
            return True

        # Open a generic application — checked last among "open ..." commands
        # so it doesn't shadow "open file", "open explorer", "open youtube" above
        open_app_match = OPEN_APP_PATTERN.match(cmd)
        if open_app_match:
            self.open_app(open_app_match.group(1).strip())
            return True

        # Shutdown
        if SHUTDOWN_PATTERN.match(cmd):
            self._skip_vocab = True
            self.speak(self._sign_off())
            self.is_running = False
            return True

        # Greeting — checked LAST among the direct-action patterns, not first.
        # GREETING_PATTERN matches "hello"/"hi"/"hey" anywhere in the string,
        # not just at the start, so it used to fire before Jupiter ever got to
        # check the more specific patterns — "translate hello to spanish" and
        # "search hello kitty toys" were both silently answered with a plain
        # greeting instead of doing what was actually asked, because GREETING
        # was checked earlier than TRANSLATE_TRIGGER_PATTERN/SEARCH_PATTERN.
        # Checking it last means every more specific command gets first
        # refusal, and a bare "hello" still falls through to here correctly
        # since nothing more specific matches it.
        greeting_match = GREETING_PATTERN.search(cmd)
        if greeting_match:
            word = greeting_match.group(1)
            if word.startswith("good"):
                self.speak(self._pick(TIMED_GREETING_REPLIES, greet=word.capitalize()))
            else:
                self.speak(self._pick(GREETING_REPLIES))
            return True

        return False  # Not a direct action → send to AI
