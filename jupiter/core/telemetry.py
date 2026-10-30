import logging
import time
from contextlib import contextmanager


logger = logging.getLogger("jupiter")


def configure_logging(log_file="logs/jupiter.log"):
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = logging.FileHandler(log_file, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
        logger.addHandler(handler)
    return logger


@contextmanager
def timed(stage: str):
    start = time.perf_counter()
    try:
        yield
    finally:
        logger.info("stage=%s duration=%.4fs", stage, time.perf_counter() - start)
