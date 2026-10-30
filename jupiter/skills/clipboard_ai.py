import re

from .base import Skill, SkillResult
from ..core.hooks import emit
from ..services.vision import VisionService, VisionError

_PAT = re.compile(r"\b(explain|fix|rewrite|proofread|improve|translate|debug|simplify)\b.*\b(clipboard|what i copied|copied text|copied code|what i just copied)\b")

_PROMPTS = {
    "explain":   "Explain the following in plain, beginner-friendly language in at most 5 short sentences.",
    "simplify":  "Explain the following in plain, beginner-friendly language in at most 5 short sentences.",
    "fix":       "The following code or text has problems. Briefly say what was wrong (max 3 sentences), then give the corrected version in ONE fenced code block.",
    "debug":     "The following code or text has problems. Briefly say what was wrong (max 3 sentences), then give the corrected version in ONE fenced code block.",
    "rewrite":   "Rewrite the following to be clearer and more professional. Output only the rewritten text.",
    "improve":   "Rewrite the following to be clearer and more professional. Output only the rewritten text.",
    "proofread": "Correct grammar and spelling in the following. Output only the corrected text.",
    "translate": "Translate the following into {lang}. Output only the translation.",
}
_REPLACING = {"rewrite", "improve", "proofread", "translate"}


class ClipboardAISkill(Skill):
    """AI actions on whatever you just copied. (Plain 'read/summarise my clipboard' stays with the original skill.)"""
    name = "clipboard_ai"
    priority = 7

    def match(self, text):
        t = text.lower().strip()
        m = _PAT.search(t)
        if not m or re.search(r"\bsummar", t):
            return None
        lang = re.search(r"\b(?:to|into)\s+(hindi|marathi|english|spanish|french|german|japanese)\b", t)
        return {"op": m.group(1), "lang": lang.group(1) if lang else "English"}

    def execute(self, args, assistant):
        who = assistant.user_name
        try:
            import pyperclip
            text = (pyperclip.paste() or "").strip()
        except Exception:
            assistant.speak(f"I can't access the clipboard, {who}.")
            return SkillResult(True, False, "clipboard", skill=self.name)
        if not text:
            assistant.speak(f"Your clipboard is empty, {who}.")
            return SkillResult(True, False, "empty", skill=self.name)
        op = args["op"]
        if not hasattr(assistant, "vision"):
            assistant.vision = VisionService(assistant)
        emit(assistant, "state", "THINKING"); emit(assistant, "log", f"Clipboard AI: {op} ({len(text)} chars)")
        try:
            out = assistant.vision.reason(_PROMPTS[op].format(lang=args["lang"]), text[:6000], num_predict=600)
        except VisionError as exc:
            assistant.speak(str(exc)); return SkillResult(True, False, str(exc), skill=self.name)
        from .vision import _speakable, _last_code_block
        assistant._last_full_text = out
        code = _last_code_block(out)
        if op in _REPLACING:
            try:
                pyperclip.copy(out); done = f" The result is on your clipboard, {who}."
            except Exception:
                done = ""
            spoken = f"Done.{done}"
        else:
            spoken, had_code = _speakable(out)
            if code:
                assistant._last_code = code
                spoken += " The corrected code is on screen. Say copy the fix, or run the fix."
        assistant.speak(spoken)
        assistant._last_response = out
        return SkillResult(True, True, out, skill=self.name)
