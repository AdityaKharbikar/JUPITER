from ..common import *


class ReminderService:
    def _parse_when(self, text: str):
        """Return (task_text, due_datetime_or_None) for a reminder phrase.

        Tries, in order: an explicit duration ('in 20 minutes'), a clock time
        ('at 6pm', 'at 18:30'), then dateparser if it happens to be installed.
        The built-in paths mean reminders work with zero extra packages.
        """
        raw = text.strip().rstrip(".!?")
        low = raw.lower()
        now = self._get_ist_time()

        # "... in 20 minutes" / "... after one minute"
        m = re.search(r'\b(?:in|after)\s+(.+)$', low)
        if m:
            seconds = self._parse_duration(m.group(1))
            if seconds:
                task = raw[:m.start()].strip().rstrip(",") or raw
                return task, now + timedelta(seconds=seconds)

        # "... at 6pm" / "... at 18:30" / "... tomorrow at 9am"
        m = re.search(r'\b(?:at|by)\s+(.+)$', low)
        if m:
            tail = m.group(1)
            clock = CLOCK_TIME_PATTERN.search(tail)
            if clock:
                if clock.group(3):                      # 12-hour with am/pm
                    hour = int(clock.group(1)) % 12
                    minute = int(clock.group(2) or 0)
                    if clock.group(3).replace(".", "").startswith("p"):
                        hour += 12
                else:                                    # 24-hour HH:MM
                    hour = int(clock.group(4))
                    minute = int(clock.group(5))
                if 0 <= hour <= 23 and 0 <= minute <= 59:
                    due = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                    if "tomorrow" in low:
                        due += timedelta(days=1)
                    elif due <= now:
                        due += timedelta(days=1)         # next occurrence
                    task = raw[:m.start()].strip().rstrip(",")
                    # Strip a trailing day word so the task reads "buy milk",
                    # not "buy milk tomorrow"
                    task = re.sub(r'\b(today|tonight|tomorrow)\s*$', '', task, flags=re.I).strip(" ,")
                    return (task or raw), due

        # Optional: let dateparser handle anything more exotic
        if dateparser_available:
            m = re.search(r'\b(?:at|by|on|in)\s+(.+)$', low)
            if m:
                try:
                    parsed = dateparser.parse(
                        m.group(1),
                        settings={
                            "PREFER_DATES_FROM": "future",
                            "TIMEZONE": "Asia/Kolkata",
                            "RETURN_AS_TIMEZONE_AWARE": True,
                        },
                    )
                    if parsed and parsed > now:
                        task = raw[:m.start()].strip().rstrip(",") or raw
                        return task, parsed
                except Exception as e:
                    print(f"[Dateparser Error] {e}")

        return raw, None

    def add_reminder(self, phrase):
        """Store a reminder, with a real due time when one can be parsed.

        Previously due_time was always 'now' and nothing ever read it back, so
        reminders were write-only. Now an unparsed reminder is stored with a
        NULL due_time (it shows up in the list but never fires), and a timed
        one is picked up by the scheduler thread.
        """
        task, due = self._parse_when(phrase)
        with self._db_lock:
            self.conn.execute(
                "INSERT INTO reminders (task, due_time, created_time) VALUES (?, ?, ?)",
                (task, due.isoformat() if due else None, self._get_ist_time().isoformat())
            )
            self.conn.commit()
        if due:
            when = due.strftime("%I:%M %p on %b %d").lstrip("0")
            self.speak(f"Reminder set for {when}, {self.user_name}: {task}")
        else:
            self.speak(
                f"Noted, {self.user_name}: {task}. I couldn\'t pin a time to that, "
                f"so I\'ll keep it on the list rather than alert you. "
                f"Add \'in 20 minutes\' or \'at 6 pm\' if you want an alert."
            )

    def list_reminders(self):
        """List active reminders, newest due first, with their alert times."""
        with self._db_lock:
            rows = self.conn.execute(
                "SELECT task, due_time FROM reminders WHERE completed = 0 "
                "ORDER BY due_time IS NULL, due_time ASC"
            ).fetchall()
        if not rows:
            self.speak(f"No active reminders, {self.user_name}.")
            return
        self.speak(f"Your reminders, {self.user_name}:")
        for i, (task, due_time) in enumerate(rows, 1):
            if due_time:
                try:
                    when = datetime.fromisoformat(due_time).strftime("%I:%M %p on %b %d").lstrip("0")
                    self.speak(f"{i}. {task} — at {when}")
                    continue
                except ValueError:
                    pass
            self.speak(f"{i}. {task} — no alert time")

    def clear_reminders(self):
        """Mark all reminders complete. Rows are kept, not deleted, so nothing
        is ever irrecoverably lost from your own database."""
        with self._db_lock:
            cursor = self.conn.execute("UPDATE reminders SET completed=1 WHERE completed=0")
            self.conn.commit()
        self.speak(f"Cleared {cursor.rowcount} reminder(s), {self.user_name}.")
