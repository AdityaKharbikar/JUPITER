"""Prepare the AI-generated demo topics BEFORE you present:
    python -m jupiter.explainer.pregen "coffee machine,washing machine"
Each topic is generated once by your local model and cached; at the demo it opens instantly.
Say "regenerate <topic>" to force a fresh, live generation (shows the progress panel)."""
import sys

from ..config import DATA_DIR, LLM_MODEL, OLLAMA_URL
from .engine import ExplainerEngine


def main(argv):
    topics = [t.strip() for t in (argv[0] if argv else "coffee machine,washing machine,telescope").split(",") if t.strip()]
    eng = ExplainerEngine(OLLAMA_URL, LLM_MODEL, DATA_DIR)
    for t in topics:
        print(f"--- {t}")
        r = eng.build(t, progress=lambda st, f, d: print(f"   [{f:4.0%}] {st}: {d}"))
        print(("OK   " if r.ok else "FAIL ") + (f"{r.title}: {r.n_parts} parts in {r.seconds:.1f}s" if r.ok else r.error))


if __name__ == "__main__":
    main(sys.argv[1:])
