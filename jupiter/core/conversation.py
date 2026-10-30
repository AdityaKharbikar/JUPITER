from ..common import *


class ConversationMixin:
    def setup_memory(self):
        """Create persistent SQLite database with conversation support"""
        self.data_dir = os.environ.get("JUPITER_DATA_DIR") or os.path.join(self.project_root, "data")
        os.makedirs(self.data_dir, exist_ok=True)
        db_path = os.path.join(self.data_dir, "jupiter_memory.db")
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        # The scheduler runs on its own thread and touches this same
        # connection. SQLite already serializes writes internally, but
        # without a generous busy timeout a write from one thread landing
        # mid-transaction on the other raises "database is locked" instead of
        # just waiting the few milliseconds it actually needs.
        self.conn.execute("PRAGMA busy_timeout = 5000")
        # Created here (not in start_scheduler) so every self.conn access
        # anywhere in the class — including ones that happen during __init__,
        # before the scheduler thread even starts — has this lock available
        # from the moment the connection exists.
        self._db_lock = threading.Lock()
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conv_id INTEGER NOT NULL DEFAULT 1,
                timestamp TEXT,
                role TEXT,
                message TEXT,
                summary TEXT
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        # Create conversation_threads table for tracking conversation metadata
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS conversation_threads (
                conv_id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT,
                summary TEXT
            )
        """)
        # Learned vocabulary. status is 'accepted' (feed it to Whisper as a
        # spelling hint) or 'rejected' (never ask about this word again).
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS vocabulary (
                word TEXT PRIMARY KEY,
                display TEXT,
                status TEXT NOT NULL DEFAULT 'accepted',
                hits INTEGER DEFAULT 1,
                added_at TEXT
            )
        """)
        # Embedded chunks of your own plain-text documents, for local Q&A.
        # Stores a copy of the text plus its vector — your originals are only
        # ever opened read-only.
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path TEXT NOT NULL,
                chunk_index INTEGER,
                text TEXT,
                embedding BLOB,
                mtime TEXT,
                indexed_at TEXT
            )
        """)
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_documents_path ON documents(path)")
        # Long-term facts the user asked Jupiter to remember ("remember that ...").
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS memory_facts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fact TEXT NOT NULL,
                created_at TEXT
            )
        """)
        # Reminder lookups run every few seconds from the scheduler thread
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task TEXT,
                due_time TEXT,
                created_time TEXT,
                completed INTEGER DEFAULT 0
            )
        """)
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_reminders_due ON reminders(completed, due_time)"
        )
        # Migrate old conversations (no conv_id) to conv_id = 1
        try:
            columns = [row[1] for row in self.conn.execute("PRAGMA table_info(conversations)")]
            if "conv_id" not in columns:
                self.conn.execute("ALTER TABLE conversations ADD COLUMN conv_id INTEGER NOT NULL DEFAULT 1")
            if "summary" not in columns:
                self.conn.execute("ALTER TABLE conversations ADD COLUMN summary TEXT")
        except sqlite3.Error as e:
            # One-time schema migration; a failure here just means the
            # columns already matched some other way. Narrowed from a bare
            # except so a real interrupt (Ctrl-C during startup) isn't
            # silently swallowed along with it.
            print(f"[Migration Note] {e}")
        self.conn.commit()

    def _get_or_create_conversation(self) -> int:
        """Load last conversation ID, or create a new one if none exists."""
        with self._db_lock:
            cursor = self.conn.execute(
                "SELECT value FROM metadata WHERE key = 'last_conv_id'"
            )
            row = cursor.fetchone()
            if row:
                conv_id = int(row[0])
                # Verify it exists in conversation_threads
                check = self.conn.execute(
                    "SELECT 1 FROM conversation_threads WHERE conv_id = ? LIMIT 1", (conv_id,)
                ).fetchone()
                if check:
                    return conv_id
            # No existing conversation — create one
            now = self._get_ist_time().isoformat()
            cursor = self.conn.execute(
                "INSERT INTO conversation_threads (created_at, summary) VALUES (?, ?)",
                (now, None)
            )
            new_id = cursor.lastrowid
            self.conn.execute(
                "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
                ("last_conv_id", str(new_id))
            )
            self.conn.commit()
            return new_id

    def set_current_conversation(self, conv_id: int):
        """Switch to a different conversation thread."""
        with self._db_lock:
            check = self.conn.execute(
                "SELECT 1 FROM conversation_threads WHERE conv_id = ? LIMIT 1", (conv_id,)
            ).fetchone()
            if check:
                self.current_conv_id = conv_id
                self.conn.execute(
                    "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
                    ("last_conv_id", str(conv_id))
                )
                self.conn.commit()
                # Get summary if exists
                summary_row = self.conn.execute(
                    "SELECT summary FROM conversation_threads WHERE conv_id = ?", (conv_id,)
                ).fetchone()
            else:
                summary_row = None
        if check:
            summary = summary_row[0] if summary_row and summary_row[0] else None
            if summary:
                self.speak(f"Switched to conversation #{conv_id}, sir. Previous summary: {summary[:100]}...")
            else:
                self.speak(f"Switched to conversation #{conv_id}, sir.")
        else:
            self.speak(f"Conversation #{conv_id} does not exist, sir.")

    def list_conversations(self):
        """Show all available conversation threads."""
        with self._db_lock:
            cursor = self.conn.execute("""
                SELECT ct.conv_id, ct.created_at, ct.summary,
                       (SELECT COUNT(*) FROM conversations c WHERE c.conv_id = ct.conv_id AND c.role IN ('user', 'jupiter')) as msgs
                FROM conversation_threads ct
                ORDER BY ct.created_at DESC
            """)
            rows = cursor.fetchall()
        if not rows:
            self.speak("No conversations found, sir.")
            return
        self.speak(f"You have {len(rows)} conversation(s), sir:")
        for conv_id, created_at, summary, msgs in rows:
            try:
                dt = datetime.fromisoformat(created_at)
                time_str = dt.strftime("%b %d, %H:%M")
            except Exception:
                time_str = created_at
            summary_msg = " (summarised)" if summary else ""
            self.speak(f"Conversation #{conv_id}: started {time_str}, {msgs} messages{summary_msg}")

    def _fetch_recent_context(self, limit: int = 6) -> list:
        """Return last exchanges from the current conversation for LLM context."""
        with self._db_lock:
            cursor = self.conn.execute("""
                SELECT role, message
                FROM conversations
                WHERE conv_id = ? AND role IN ('user', 'jupiter')
                ORDER BY id DESC
                LIMIT ?
            """, (self.current_conv_id, limit))
            rows = cursor.fetchall()
        # Ollama's chat API expects {"role", "content"} and only recognizes
        # "system"/"user"/"assistant" — map our stored "jupiter" role accordingly.
        return [
            {"role": "assistant" if r == "jupiter" else r, "content": m}
            for r, m in reversed(rows)
        ]

    def _get_conversation_summary(self) -> str:
        """Get stored summary for current conversation."""
        with self._db_lock:
            cursor = self.conn.execute(
                "SELECT summary FROM conversation_threads WHERE conv_id = ?",
                (self.current_conv_id,)
            )
            row = cursor.fetchone()
        return row[0] if row and row[0] else ""

    def _get_previous_conversation_id(self):
        """Return the conv_id of the conversation thread immediately before the
        current one (by creation order), or None if there isn't one."""
        with self._db_lock:
            cursor = self.conn.execute(
                "SELECT conv_id FROM conversation_threads WHERE conv_id < ? ORDER BY conv_id DESC LIMIT 1",
                (self.current_conv_id,)
            )
            row = cursor.fetchone()
        return row[0] if row else None

    def _get_or_generate_summary(self, conv_id: int):
        """Return a conversation's stored summary, generating and caching one on
        the fly if it doesn't have one yet. Returns None if it has no messages."""
        with self._db_lock:
            cursor = self.conn.execute(
                "SELECT summary FROM conversation_threads WHERE conv_id = ?", (conv_id,)
            )
            row = cursor.fetchone()
        if row and row[0]:
            return row[0]

        conv_text = self._fetch_conversation_text(conv_id)
        if not conv_text:
            return None

        summary = self._call_summary_api(conv_text)
        if summary:
            with self._db_lock:
                self.conn.execute(
                    "UPDATE conversation_threads SET summary = ? WHERE conv_id = ?",
                    (summary, conv_id)
                )
                self.conn.commit()
        return summary

    def _fetch_conversation_text(self, conv_id: int):
        """Return the full transcript of a conversation as 'role: message' lines,
        or None if it has no messages yet."""
        with self._db_lock:
            cursor = self.conn.execute("""
                SELECT role, message
                FROM conversations
                WHERE conv_id = ? AND role IN ('user', 'jupiter')
                ORDER BY id ASC
            """, (conv_id,))
            rows = cursor.fetchall()
        if not rows:
            return None
        return "\n".join([f"{role}: {msg}" for role, msg in rows])

    def _call_summary_api(self, conv_text: str):
        """Ask the LLM to summarise a transcript in 2-3 sentences. Returns None on failure."""
        summary_prompt = f"Summarise this conversation concisely in 2-3 sentences:\n\n{conv_text}"
        try:
            response = self.http.post(
                self.ollama_url,
                json={
                    "model": LLM_MODEL, "think": False,
                    "messages": [
                        {"role": "system", "content": "You are a helpful assistant that summarises conversations. Provide brief, clear summaries."},
                        {"role": "user", "content": summary_prompt}
                    ],
                    "stream": False,
                    "keep_alive": "30m",
                    "options": {"temperature": 0.3, "num_predict": 100}
                },
                timeout=30
            )
            if response.status_code == 200:
                return response.json()["message"]["content"].strip()
            return None
        except Exception:
            return None

    def summarise_conversation(self):
        """Generate and store a summary of the current conversation, and speak it."""
        conv_text = self._fetch_conversation_text(self.current_conv_id)
        if conv_text is None:
            self.speak(f"No messages to summarise in this conversation, {self.user_name}.")
            return

        summary = self._call_summary_api(conv_text)
        if summary is None:
            self.speak(f"Failed to generate summary, {self.user_name}.")
            return

        with self._db_lock:
            self.conn.execute(
                "UPDATE conversation_threads SET summary = ? WHERE conv_id = ?",
                (summary, self.current_conv_id)
            )
            self.conn.commit()
        self.speak(f"Conversation summarised, {self.user_name}: {summary}")

    def remember_fact(self, fact: str):
        fact = fact.strip().rstrip(".!?").strip()[:300]
        if not fact:
            self.speak(f"What should I remember, {self.user_name}?")
            return
        with self._db_lock:
            exists = self.conn.execute(
                "SELECT 1 FROM memory_facts WHERE lower(fact) = ? LIMIT 1", (fact.lower(),)
            ).fetchone()
            if not exists:
                self.conn.execute(
                    "INSERT INTO memory_facts (fact, created_at) VALUES (?, ?)",
                    (fact, self._get_ist_time().isoformat())
                )
                self.conn.commit()
        if exists:
            self.speak(f"I already have that one, {self.user_name}.")
        else:
            self.speak(self._pick(MEMORY_SAVED))

    def _facts_for_prompt(self) -> str:
        try:
            with self._db_lock:
                rows = self.conn.execute(
                    "SELECT fact FROM memory_facts ORDER BY id DESC LIMIT 20"
                ).fetchall()
        except sqlite3.Error:
            return ""
        return "\n".join(f"- {r[0]}" for r in reversed(rows))

    def recall_facts(self):
        with self._db_lock:
            rows = self.conn.execute("SELECT fact FROM memory_facts ORDER BY id ASC").fetchall()
        if not rows:
            self.speak(f"I'm not holding on to anything yet, {self.user_name}. Say 'remember that' followed by a fact.")
            return
        for i, (fact,) in enumerate(rows, 1):
            print(f"  {i}. {fact}")
        spoken = "; ".join(f for (f,) in rows[-8:])
        more = f" Showing the latest {min(8, len(rows))} of {len(rows)}." if len(rows) > 8 else ""
        self.speak(f"I remember {len(rows)} thing(s), {self.user_name}: {spoken}.{more}")

    def forget_facts(self):
        with self._db_lock:
            count = self.conn.execute("SELECT COUNT(*) FROM memory_facts").fetchone()[0]
        if not count:
            self.speak(f"There's nothing to forget, {self.user_name}.")
            return
        answer = self.ask_yes_no(f"That will erase {count} remembered fact(s), {self.user_name}. Are you sure?")
        if answer is True:
            with self._db_lock:
                self.conn.execute("DELETE FROM memory_facts")
                self.conn.commit()
            self.speak(f"Done, {self.user_name}. My long-term memory is cleared.")
        else:
            self.speak(f"Alright, I'll keep them, {self.user_name}.")

    def recall_discussion(self, cmd: str):
        """'What did we talk about?' -> this conversation's summary, or the
        previous conversation's if the question reaches back ('last time')."""
        if RECALL_EARLIER_WORDS.search(cmd):
            prev = self._get_previous_conversation_id()
            summary = self._get_or_generate_summary(prev) if prev is not None else None
            if summary:
                self.speak(f"Last time we spoke, {self.user_name}: {summary}")
            else:
                self.speak(f"I don't have an earlier conversation to recall, {self.user_name}.")
        else:
            self.summarise_conversation()

    def store_conversation(self, role: str, message: str):
        """Persist a single utterance in the current conversation."""
        # Guarded by _db_lock: the scheduler thread also touches self.conn
        # (reminders), and sqlite3 connections aren't safe to use from two
        # threads at once without serialising access like this.
        with self._db_lock:
            self.conn.execute(
                """
                INSERT INTO conversations (conv_id, timestamp, role, message)
                VALUES (?, ?, ?, ?)
                """,
                (self.current_conv_id, self._get_ist_time().isoformat(), role, message)
            )
            self.conn.commit()
