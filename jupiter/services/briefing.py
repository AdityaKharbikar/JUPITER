"""Facts for the JARVIS-style briefing and the GUI memory panel. Pure Python, no LLM."""
import datetime as _dt

try:
    import psutil
except ImportError:           # pragma: no cover
    psutil = None


def snapshot(a, fresh_cpu: bool = False) -> dict:
    d = {"cpu": None, "ram": None, "battery": None, "plugged": None,
         "tasks": [], "task_count": 0, "next_reminder": None, "facts": [], "mode": getattr(a, "current_mode", "normal")}
    if psutil:
        try:
            d["cpu"] = psutil.cpu_percent(interval=0.3 if fresh_cpu else None)
            d["ram"] = psutil.virtual_memory().percent
            b = psutil.sensors_battery()
            if b:
                d["battery"], d["plugged"] = int(b.percent), bool(b.power_plugged)
        except Exception:
            pass
    try:
        if hasattr(a, "setup_productivity"):
            a.setup_productivity()          # makes sure the tasks table exists
        with a._db_lock:
            rows = a.conn.execute(
                "SELECT title FROM tasks WHERE status='open' ORDER BY priority, id LIMIT 3").fetchall()
            d["tasks"] = [r[0] for r in rows]
            d["task_count"] = a.conn.execute("SELECT COUNT(*) FROM tasks WHERE status='open'").fetchone()[0]
            r = a.conn.execute(
                "SELECT task, due_time FROM reminders WHERE completed=0 AND due_time IS NOT NULL "
                "ORDER BY due_time LIMIT 1").fetchone()
            if r:
                d["next_reminder"] = (r[0], r[1])
            d["facts"] = [x[0] for x in a.conn.execute(
                "SELECT fact FROM memory_facts ORDER BY id DESC LIMIT 4").fetchall()]
    except Exception as exc:
        print(f"[Briefing] db read failed: {exc}")
    return d


def _time_phrase(iso: str) -> str:
    try:
        return _dt.datetime.fromisoformat(iso).strftime("%I:%M %p").lstrip("0")
    except Exception:
        return iso


def compose(a) -> str:
    s = snapshot(a, fresh_cpu=True)
    who = a.user_name
    parts = [f"Good {a._greeting_period()}, {who}."]
    health = "System health is normal"
    if s["ram"] is not None and (s["ram"] > 85 or (s["cpu"] or 0) > 90):
        health = "System load is high"
    if s["cpu"] is not None:
        health += f": CPU {s['cpu']:.0f} percent, RAM {s['ram']:.0f} percent"
    parts.append(health + ".")
    if s["battery"] is not None:
        parts.append(f"Battery is at {s['battery']} percent{' and charging' if s['plugged'] else ''}.")
    n = s["task_count"]
    if n:
        parts.append(f"You have {n} open task{'s' if n != 1 else ''}; the top one is {s['tasks'][0]}.")
    else:
        parts.append("You have no open tasks.")
    if s["next_reminder"]:
        parts.append(f"Your next reminder is at {_time_phrase(s['next_reminder'][1])}: {s['next_reminder'][0]}.")
    if s["facts"]:
        parts.append(f"I'm also remembering: {s['facts'][0]}.")
    parts.append("Ready when you are.")
    return " ".join(parts)
