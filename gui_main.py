import os
import sys

from jupiter.ui.desktop import launch

if __name__ == "__main__":
    code = launch()
    try:
        sys.stdout.flush(); sys.stderr.flush()
    except Exception:
        pass
    # Daemon threads blocked in PortAudio / CUDA can keep the interpreter alive
    # during normal teardown; everything has already been shut down, so leave now.
    os._exit(int(code or 0))
