import re

from .base import Skill, SkillResult
from ..services.control import ControlService, SAFE_KEYS, _KEY_ALIASES

_RULES = [
    ("show_desktop", r"^(?:show|go to) (?:the |my )?desktop$|^minimi[sz]e (?:all|everything)(?: windows)?$"),
    ("switch_window", r"^(?:switch|change|next) (?:the )?window$|^alt tab$"),
    ("snap_left", r"^snap (?:this |the )?(?:window )?left$|^window left$"),
    ("snap_right", r"^snap (?:this |the )?(?:window )?right$|^window right$"),
    ("maximize", r"^maximi[sz]e (?:this |the )?window$"),
    ("new_tab", r"^(?:open |new )(?:a )?(?:new )?tab$"),
    ("close_tab", r"^close (?:this |the )?tab$"),
    ("close_window", r"^close (?:this |the |active )?window$"),
    ("refresh", r"^refresh(?: the page| this page)?$|^reload (?:the |this )?page$"),
    ("lock", r"^lock (?:the |my )?(?:computer|pc|laptop|screen)$"),
    ("screenshot", r"^(?:take|capture|save) (?:a )?screenshot$|^screenshot$"),
    ("active_window", r"^(?:what app|which app|what window|which window) (?:is|am i using|is active)$|^active window$|^what(?:'s| is) active$"),
]
_SCROLL = re.compile(r"^scroll (up|down)(?: a bit| a little| more)?$")
_PRESS = re.compile(r"^press (?:the )?(.+?)(?: key| button)?$")
_TYPE = re.compile(r"^(?:type out|dictate|type this)[: ]+(.+)$", re.I)


class ControlSkill(Skill):
    """Exact-phrase matching on purpose: a desktop-control command must never fire from a half-heard sentence."""
    name = "control"
    priority = 9

    def match(self, text):
        t = text.lower().strip().strip(".!?, ")
        t = re.sub(r"^(?:jupiter[, ]+|please |can you |could you )+", "", t)
        for op, pat in _RULES:
            if re.match(pat, t):
                return {"op": op}
        m = _SCROLL.match(t)
        if m:
            return {"op": "scroll", "dir": m.group(1)}
        m = _PRESS.match(t)
        if m and _KEY_ALIASES.get(m.group(1), m.group(1)) in SAFE_KEYS:
            return {"op": "key", "key": m.group(1)}
        m = _TYPE.match(re.sub(r"^(?:jupiter[, ]+|please )+", "", text.strip().strip(".!?, "), flags=re.I))
        if m:
            return {"op": "type", "text": m.group(1)}
        return None

    def execute(self, args, assistant):
        if not hasattr(assistant, "control"):
            assistant.control = ControlService(assistant)
        c, op = assistant.control, args["op"]
        if op == "scroll":
            c.scroll(args["dir"])
        elif op == "key":
            c.press_key(args["key"])
        elif op == "type":
            c.type_text(args["text"])
        elif op == "screenshot":
            c.screenshot()
        elif op == "active_window":
            c.active_window_title()
        elif op == "lock":
            c.lock()
        else:
            c.hotkey(op)
        return SkillResult(True, True, op, skill=self.name)
