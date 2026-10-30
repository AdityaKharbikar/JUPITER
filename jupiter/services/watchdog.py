"""Proactive watchdog: plain Python watches the machine, JUPITER speaks only when it matters.
No LLM is involved, so it costs nothing while idle."""
import threading
import time
from collections import defaultdict

try:
    import psutil
except ImportError:           # pragma: no cover
    psutil = None

from ..core.hooks import emit


class Watchdog:
    def __init__(self, assistant, interval=20, cooldown=600,
                 ram_limit=88, cpu_limit=92, battery_low=20, battery_critical=10, break_after=5400):
        self.a = assistant
        self.interval, self.cooldown = interval, cooldown
        self.ram_limit, self.cpu_limit = ram_limit, cpu_limit
        self.battery_low, self.battery_critical = battery_low, battery_critical
        self.break_after = break_after
        self.enabled = True
        self._stop = threading.Event()
        self._last = defaultdict(float)
        self._cpu_hits = 0
        self._thread = None

    def start(self):
        if psutil is None or self._thread:
            return
        self._thread = threading.Thread(target=self._loop, name="jupiter-watchdog", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _alert(self, key: str, text: str, cooldown: float | None = None):
        now = time.time()
        if not self.enabled or now - self._last[key] < (cooldown or self.cooldown):
            return
        self._last[key] = now
        emit(self.a, "alert", text)
        self.a._announce(text)            # queued; spoken by the main loop / GUI drain

    def _top_process(self):
        usage = defaultdict(int)
        for p in psutil.process_iter(["name", "memory_info"]):
            try:
                usage[(p.info["name"] or "?").lower().replace(".exe", "")] += p.info["memory_info"].rss
            except Exception:
                continue
        if not usage:
            return None
        name = max(usage, key=usage.get)
        return name, usage[name] / 1073741824

    def check_once(self):
        who = self.a.user_name
        mem = psutil.virtual_memory().percent
        if mem >= self.ram_limit:
            top = self._top_process()
            extra = f" {top[0]} is using {top[1]:.1f} gigabytes." if top else ""
            self._alert("ram", f"Warning, {who}. Memory usage has reached {mem:.0f} percent.{extra}")
        cpu = psutil.cpu_percent(interval=1.0)
        self._cpu_hits = self._cpu_hits + 1 if cpu >= self.cpu_limit else 0
        if self._cpu_hits >= 3:
            self._alert("cpu", f"CPU has been above {self.cpu_limit} percent for a while, {who}.")
        self._break_nudge(who)
        b = psutil.sensors_battery()
        if b and not b.power_plugged:
            if b.percent <= self.battery_critical:
                self._alert("batt_crit", f"Battery is critically low at {int(b.percent)} percent, {who}. Please plug in.")
            elif b.percent <= self.battery_low:
                self._alert("batt_low", f"Battery is at {int(b.percent)} percent, {who}.")

    def _break_nudge(self, who):
        """If you've been chatting with JUPITER in one long stretch (gaps < 15 min), suggest a break."""
        start, last = getattr(self.a, "_streak_start", None), getattr(self.a, "_last_turn_ts", None)
        if not start or not last:
            return
        now = time.time()
        if now - last < 900 and now - start >= self.break_after:
            mins = int((now - start) / 60)
            self._alert("break", f"You've been working for about {mins} minutes, {who}. Consider a short break.", cooldown=self.break_after)

    def _loop(self):
        while not self._stop.wait(self.interval):
            try:
                self.check_once()
            except Exception as exc:
                print(f"[Watchdog] {exc}")
