from ..common import *


class TimerService:
    def _words_to_digits(self, text: str) -> str:
        """Replace spoken number words ('one', 'thirty') with digits so
        DURATION_PATTERN's \\d+ can find them."""
        return NUMBER_WORD_PATTERN.sub(lambda m: str(NUMBER_WORDS[m.group(1).lower()]), text)

    def _parse_duration(self, text: str):
        """Turn '10 minutes', '1 hour 30 mins', '90s', or 'one minute' into
        seconds. Returns None if nothing duration-like is present."""
        total = 0
        found = False
        text = self._words_to_digits(text.lower())
        for amount, unit in DURATION_PATTERN.findall(text):
            mult = DURATION_UNITS.get(unit.rstrip("."), None)
            if mult is None:
                mult = DURATION_UNITS.get(unit.rstrip("s"), None)
            if mult is None:
                continue
            total += float(amount) * mult
            found = True
        if not found or total <= 0:
            return None
        # Sanity cap: 30 days. Anything longer is almost certainly a misparse.
        return min(total, 30 * 86400)

    def _humanise_delta(self, seconds: float) -> str:
        seconds = int(max(0, seconds))
        if seconds < 60:
            return f"{seconds} second{'s' if seconds != 1 else ''}"
        parts = []
        # Walk hour -> minute -> second so leftover seconds are announced too
        # instead of being silently dropped (90s used to read as "1 minute").
        for label, size in (("hour", 3600), ("minute", 60), ("second", 1)):
            if seconds >= size:
                value, seconds = divmod(seconds, size)
                parts.append(f"{value} {label}{'s' if value != 1 else ''}")
        if not parts:
            return "less than a second"
        if len(parts) == 1:
            return parts[0]
        return ", ".join(parts[:-1]) + " and " + parts[-1]

    def set_timer(self, phrase: str):
        seconds = self._parse_duration(phrase)
        if not seconds:
            self.speak(f"I couldn't work out a duration from that, {self.user_name}. Try: set a timer for 10 minutes.")
            return
        # Remove the duration itself, then a leading/trailing "for" as a WORD.
        # (An earlier version used strip(" ,.for"), which strips those
        # characters individually and turned "dinner" into "dinne".)
        label = DURATION_PATTERN.sub("", phrase)
        label = re.sub(r'^(?:\s*for\b)+|(?:\bfor\s*)+$', '', label).strip(" ,.")
        label = label or self._humanise_delta(seconds)
        with self._timers_lock:
            self._timers.append({
                "label": label,
                "due": self._get_ist_time() + timedelta(seconds=seconds),
                "seconds": seconds,
            })
        self.speak(f"Timer set for {self._humanise_delta(seconds)}, {self.user_name}.")

    def list_timers(self):
        with self._timers_lock:
            timers_snapshot = list(self._timers)
        if not timers_snapshot:
            self.speak(f"No timers running, {self.user_name}.")
            return
        now = self._get_ist_time()
        self.speak(f"{len(timers_snapshot)} timer(s) running, {self.user_name}:")
        for t in timers_snapshot:
            left = (t["due"] - now).total_seconds()
            self.speak(f"{t['label']}: {self._humanise_delta(left)} left.")

    def cancel_timers(self):
        with self._timers_lock:
            count = len(self._timers)
            self._timers.clear()
        if count:
            self.speak(f"Cancelled {count} timer(s), {self.user_name}.")
        else:
            self.speak(f"There were no timers to cancel, {self.user_name}.")

    def start_stopwatch(self):
        self._stopwatch_start = time.monotonic()
        self.speak(f"Stopwatch started, {self.user_name}.")

    def read_stopwatch(self, stop: bool = False):
        if self._stopwatch_start is None:
            self.speak(f"The stopwatch isn't running, {self.user_name}.")
            return
        elapsed = time.monotonic() - self._stopwatch_start
        if stop:
            self._stopwatch_start = None
            self.speak(f"Stopped at {self._humanise_delta(elapsed)}, {self.user_name}.")
        else:
            self.speak(f"{self._humanise_delta(elapsed)} so far, {self.user_name}.")
