"""Migration check: every method of the ORIGINAL monolithic Jupiter must exist on the ASSEMBLED class.

The old version of this script only looked for a `def` with the right name anywhere in the source,
so a method accidentally nested inside another function (or de-indented out of its class) still
counted as 'mapped'. This one imports the real class and checks attribute access instead.
"""
from pathlib import Path
import ast
import sys

ORIGINAL = Path("jupiter_try2_reference.py")
orig = ast.parse(ORIGINAL.read_text(encoding="utf-8"))
cls = next(n for n in orig.body if isinstance(n, ast.ClassDef) and n.name == "Jupiter")
original_methods = sorted(m.name for m in cls.body if isinstance(m, ast.FunctionDef))

sys.path.insert(0, str(Path(__file__).resolve().parent))
from jupiter.core.assistant import Jupiter  # noqa: E402

missing = [n for n in original_methods if not hasattr(Jupiter, n)]
print(f"Original Jupiter methods: {len(original_methods)}")
print(f"Present on the assembled Jupiter class: {len(original_methods) - len(missing)}")
print("Missing:", missing)
raise SystemExit(1 if missing else 0)
