"""Lightweight, honest performance log.

Every call to ``record`` appends one JSON line to logs/metrics.jsonl:
  ts, op, model, cache_hit, ttfo_s (time to first visible output), total_s, ok, detail
``summary()`` / ``report_markdown()`` aggregate whatever was REALLY measured on this machine - nothing is invented.
"""
from __future__ import annotations

import json
import statistics
import threading
import time
from pathlib import Path

_LOCK = threading.Lock()


class Metrics:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, op, *, model="", cache_hit=None, ttfo_s=None, total_s=None, ok=True, detail=""):
        row = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"), "op": op, "model": model or "",
               "cache_hit": cache_hit, "ttfo_s": None if ttfo_s is None else round(ttfo_s, 3),
               "total_s": None if total_s is None else round(total_s, 3), "ok": bool(ok), "detail": str(detail)[:160]}
        try:
            with _LOCK, self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        except OSError:
            pass
        return row

    def rows(self, limit=None):
        out = []
        try:
            with self.path.open(encoding="utf-8") as f:
                for line in f:
                    try:
                        out.append(json.loads(line))
                    except ValueError:
                        continue
        except OSError:
            return []
        return out[-limit:] if limit else out

    def summary(self, limit=500):
        groups: dict = {}
        for r in self.rows(limit):
            key = (r.get("op"), "cache hit" if r.get("cache_hit") else ("cache miss" if r.get("cache_hit") is False else "-"))
            groups.setdefault(key, []).append(r)
        res = []
        for (op, cache), rs in sorted(groups.items(), key=lambda kv: str(kv[0])):
            tot = [r["total_s"] for r in rs if r.get("total_s") is not None]
            first = [r["ttfo_s"] for r in rs if r.get("ttfo_s") is not None]
            res.append({"op": op, "cache": cache, "runs": len(rs), "ok": sum(1 for r in rs if r.get("ok")),
                        "ttfo_median": statistics.median(first) if first else None,
                        "total_median": statistics.median(tot) if tot else None,
                        "total_max": max(tot) if tot else None,
                        "models": sorted({r.get("model") for r in rs if r.get("model")})})
        return res

    def report_markdown(self, limit=500):
        rows = self.summary(limit)
        if not rows:
            return "No measurements recorded yet."
        f = lambda v: "-" if v is None else f"{v:.2f}s"
        lines = ["| Operation | Cache | Runs | OK | First output (median) | Total (median) | Total (max) | Model |", "|---|---|---|---|---|---|---|---|"]
        for r in rows:
            lines.append(f"| {r['op']} | {r['cache']} | {r['runs']} | {r['ok']} | {f(r['ttfo_median'])} | {f(r['total_median'])} | {f(r['total_max'])} | {', '.join(r['models']) or '-'} |")
        return "\n".join(lines)

    def spoken_summary(self):
        rows = [r for r in self.summary() if r["total_median"] is not None]
        if not rows:
            return "I have no measurements yet."
        parts = []
        for r in rows[:4]:
            parts.append(f"{r['op'].replace('.', ' ')} {r['cache']}: {r['total_median']:.1f} seconds median over {r['runs']} runs")
        return "; ".join(parts) + "."
