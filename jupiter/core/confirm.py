"""Permission layer: risky actions are PROPOSED, then run only after the user says yes.

    propose(assistant, "run this code in the sandbox", fn)      # speaks the question
    ... next turn the user says "confirm" / "go ahead" / "cancel" ...

State is module-level so a skill's match() (which has no assistant) can ask
"is something waiting for an answer?". A proposal expires after 60 seconds.
"""
import re
import time
from dataclasses import dataclass
from typing import Callable

from .hooks import emit

TTL = 60.0


@dataclass
class Pending:
    description: str
    run: Callable[[], None]
    created: float


_pending: Pending | None = None

YES = re.compile(r"^(?:jupiter[, ]*)?(?:yes|yeah|yep|confirm|confirmed|go ahead|proceed|do it|run it|sure|okay|ok|affirmative)\b")
NO = re.compile(r"^(?:jupiter[, ]*)?(?:no|nope|cancel|abort|stop|don'?t|never mind|nevermind|negative)\b")


def current() -> Pending | None:
    global _pending
    if _pending and time.time() - _pending.created > TTL:
        _pending = None
    return _pending


def propose(assistant, description: str, run: Callable[[], None], prompt: str | None = None):
    global _pending
    _pending = Pending(description, run, time.time())
    emit(assistant, "confirm", description)
    assistant.speak(prompt or f"I'm about to {description}. Say confirm to proceed, or cancel.")


def clear(assistant=None):
    global _pending
    _pending = None
    if assistant is not None:
        emit(assistant, "confirm", "")


def answer(assistant, yes: bool):
    """Resolve the pending action. Returns True if there was one."""
    p = current()
    if p is None:
        return False
    clear(assistant)
    if yes:
        p.run()
    else:
        assistant.speak(f"Cancelled, {assistant.user_name}.")
    return True
