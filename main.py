import os
import sys

from jupiter.core.assistant import Jupiter


def main():
    assistant = Jupiter()
    try:
        assistant.run()
    finally:
        try:
            assistant.shutdown()
        except Exception:
            pass


if __name__ == "__main__":
    main()
    try:
        sys.stdout.flush(); sys.stderr.flush()
    except Exception:
        pass
    # "quit" must really end the process: lingering audio / CUDA / worker threads
    # can otherwise keep it alive after the sign-off.
    os._exit(0)
