from ..common import *


class SchedulerService:
    def start_scheduler(self):
        """Start the daemon thread that watches for due reminders and timers."""
        self._events = queue.Queue()
        self._timers = []          # list of dicts: {"label", "due", "seconds"}
        self._timers_lock = threading.Lock()  # guards _timers across threads
        self._stopwatch_start = None
        self._scheduler_stop = threading.Event()
        # _db_lock is created earlier, in setup_memory(), not here — see the
        # comment there for why.
        self._scheduler = threading.Thread(
            target=self._scheduler_loop, name="jupiter-scheduler", daemon=True
        )
        self._scheduler.start()

    def _scheduler_loop(self):
        """Poll every few seconds. Daemon thread, so it can never keep Python
        alive after you quit, and every iteration is wrapped so a transient DB
        or clock error can't kill the loop."""
        # 2 seconds is responsive enough for timers without being busy work:
        # one tiny indexed SQLite query per tick, which is far below noise.
        while not self._scheduler_stop.wait(2.0):
            try:
                now = self._get_ist_time()

                # Timers live in memory only — they're session-scoped by design
                with self._timers_lock:
                    due_timers = [t for t in self._timers if now >= t["due"]]
                    for t in due_timers:
                        self._timers.remove(t)
                for t in due_timers:
                    self._announce(f"Timer finished: {t['label']}.")

                # Reminders live in SQLite and survive restarts
                with self._db_lock:
                    rows = self.conn.execute(
                        "SELECT id, task FROM reminders "
                        "WHERE completed = 0 AND due_time IS NOT NULL AND due_time <= ?",
                        (now.isoformat(),)
                    ).fetchall()
                    for rid, task in rows:
                        self.conn.execute(
                            "UPDATE reminders SET completed = 1 WHERE id = ?", (rid,)
                        )
                    if rows:
                        self.conn.commit()
                for _, task in rows:
                    self._announce(f"Reminder, {self.user_name}: {task}.")
            except Exception as e:
                print(f"[Scheduler Error] {e}")

    def _announce(self, text: str):
        """Queue something for the main loop to speak, and print it right away
        so you see it even while Jupiter is blocked on input()."""
        print(f"\n[JUPITER] {text}")
        try:
            self._events.put_nowait(text)
        except Exception:
            pass

    def drain_events(self):
        """Speak anything the scheduler queued. Called by the main loop only."""
        while True:
            try:
                text = self._events.get_nowait()
            except queue.Empty:
                return
            except Exception:
                return
            self.speak(text)
