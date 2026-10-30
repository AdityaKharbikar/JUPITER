import subprocess
import sys


def run(label, args):
    print(f"\n== {label} ==")
    p = subprocess.run([sys.executable, *args], text=True)
    if p.returncode != 0:
        raise SystemExit(p.returncode)


if __name__ == "__main__":
    run("Python compilation", ["-m", "compileall", "-q", "."])
    run("Automated tests", ["-m", "pytest", "-q", "--import-mode=importlib"])
    run("149-method migration check (real class introspection)", ["check_mapping.py"])
    if "--doctor" in sys.argv:
        run("Runtime doctor", ["doctor.py"])
    else:
        print("\nPASS: code, tests and migration checks are clean.")
        print("Run `python self_check.py --doctor` on the real Windows laptop for hardware/Ollama/audio checks.")
