"""Run a Python snippet in a throw-away folder with a time limit.

HONEST LABEL: this is a guard-rail, not a hardened sandbox. Layers:
  1. static AST scan refuses obviously dangerous code (network, subprocess, file deletion/writes, eval...),
  2. the user must confirm after seeing the code (see core/confirm.py),
  3. runs in `python -I` inside data/sandbox with a 10 s timeout and capped output.
"""
import ast
import os
import subprocess
import sys
import tempfile

BLOCKED_IMPORTS = {"subprocess", "socket", "ctypes", "shutil", "requests", "urllib", "http", "ftplib",
                   "smtplib", "multiprocessing", "pty", "winreg", "webbrowser", "pyautogui", "telnetlib"}
BLOCKED_CALLS = {"eval", "exec", "compile", "__import__", "input"}
BLOCKED_ATTRS = {"system", "popen", "remove", "unlink", "rmdir", "removedirs", "rename", "replace", "kill",
                 "startfile", "rmtree", "write_text", "write_bytes", "chmod", "chown", "execv", "execl", "spawnl"}
MAX_OUT = 1500


def scan(code: str):
    """Return (ok, reason)."""
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return False, f"it has a syntax error on line {exc.lineno}"
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for n in node.names:
                if n.name.split(".")[0] in BLOCKED_IMPORTS:
                    return False, f"it imports {n.name}"
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] in BLOCKED_IMPORTS:
                return False, f"it imports {node.module}"
        elif isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Name) and f.id in BLOCKED_CALLS:
                return False, f"it calls {f.id}()"
            if isinstance(f, ast.Attribute) and f.attr in BLOCKED_ATTRS:
                return False, f"it calls .{f.attr}()"
            if isinstance(f, ast.Name) and f.id == "open":
                mode = ""
                if len(node.args) > 1 and isinstance(node.args[1], ast.Constant):
                    mode = str(node.args[1].value)
                for kw in node.keywords:
                    if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
                        mode = str(kw.value.value)
                if any(c in mode for c in "wax+"):
                    return False, "it writes to a file"
    return True, ""


def run(code: str, sandbox_dir: str, timeout: int = 10) -> dict:
    os.makedirs(sandbox_dir, exist_ok=True)
    ok, why = scan(code)
    if not ok:
        return {"ok": False, "refused": True, "output": f"Refused: {why}."}
    fd, path = tempfile.mkstemp(suffix=".py", dir=sandbox_dir)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(code)
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        p = subprocess.run([sys.executable, "-I", path], cwd=sandbox_dir, capture_output=True, text=True,
                           timeout=timeout, creationflags=flags)
        out = (p.stdout or "") + (p.stderr or "")
        return {"ok": p.returncode == 0, "refused": False, "output": out.strip()[:MAX_OUT] or "(no output)"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "refused": False, "output": f"Stopped after {timeout} seconds (possible infinite loop)."}
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
