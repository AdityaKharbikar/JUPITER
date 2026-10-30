"""Measure the explainer on THIS machine:  python -m jupiter.explainer.benchmark [--llm] [--topics "ceiling fan,telescope"]

Writes BENCHMARK_REPORT.md next to the project. Numbers come only from real runs - nothing is estimated.
"""
from __future__ import annotations

import argparse
import os
import statistics
import sys
import time
from pathlib import Path

import requests

from ..config import DATA_DIR, LLM_MODEL, OLLAMA_URL
from ..core.metrics import Metrics
from . import library
from .engine import ExplainerEngine

DEFAULT_LLM_TOPICS = ["ceiling fan", "coffee machine", "telescope"]


def run(llm=False, topics=None, out=None):
    root = Path(DATA_DIR).parent
    metrics = Metrics(root / "logs" / "benchmark_metrics.jsonl")
    eng = ExplainerEngine(OLLAMA_URL, LLM_MODEL, DATA_DIR, metrics)
    lines = [f"# JUPITER benchmark - {time.strftime('%Y-%m-%d %H:%M')}", "", f"Machine: {os.environ.get('COMPUTERNAME', 'unknown')} · Python {sys.version.split()[0]}", ""]
    # 1) curated models: cold (HTML rebuilt) vs warm (HTML pre-generated)
    cold, warm = [], []
    rows = ["| Model | Parts | Cold build | Warm open |", "|---|---|---|---|"]
    for entry in library.catalog():
        html = eng._html_path("cur_" + entry["key"])
        if html.exists():
            html.unlink()
        r1 = eng.build(entry["topic"])
        r2 = eng.build(entry["topic"])
        cold.append(r1.seconds); warm.append(r2.seconds)
        rows.append(f"| {entry['topic']} | {r1.n_parts} | {r1.seconds * 1000:.1f} ms | {r2.seconds * 1000:.1f} ms |")
    lines += ["## Curated models (no AI involved)", "", *rows, "",
              f"Median cold build {statistics.median(cold) * 1000:.1f} ms, median warm open {statistics.median(warm) * 1000:.1f} ms.", ""]
    # 2) AI generation (needs Ollama)
    if llm:
        base = OLLAMA_URL.rsplit("/api/", 1)[0]
        try:
            requests.get(base + "/api/tags", timeout=3).raise_for_status()
            reachable = True
        except Exception:
            reachable = False
        lines += ["## AI-generated models", ""]
        if not reachable:
            lines.append("Ollama is not reachable - skipped (start it with `ollama serve`).")
        else:
            lines += [f"Model: `{LLM_MODEL}`", "", "| Topic | Result | First component | Total (generate) | Total (cached) |", "|---|---|---|---|---|"]
            for t in (topics or DEFAULT_LLM_TOPICS):
                first = eng.build(t, force_new=True)
                ttfo = [r for r in metrics.rows() if r["op"] == "explainer.build"][-1].get("ttfo_s")
                second = eng.build(t)
                ok = "ok" if first.ok else f"FAILED: {first.error}"
                lines.append(f"| {t} | {ok} ({first.n_parts} parts) | {('%.1fs' % ttfo) if ttfo else '-'} | {first.seconds:.1f}s | {second.seconds * 1000:.1f} ms |")
    lines += ["", "## Raw summary from logs/benchmark_metrics.jsonl", "", metrics.report_markdown()]
    text = "\n".join(lines)
    out = Path(out) if out else root / "BENCHMARK_REPORT.md"
    out.write_text(text, encoding="utf-8")
    print(text)
    print(f"\nSaved to {out}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm", action="store_true", help="also time AI generation (needs Ollama running)")
    ap.add_argument("--topics", default="", help="comma separated topics for the AI part")
    a = ap.parse_args()
    run(a.llm, [t.strip() for t in a.topics.split(",") if t.strip()] or None)
