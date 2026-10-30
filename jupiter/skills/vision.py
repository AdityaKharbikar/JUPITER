import re
import time

from .base import Skill, SkillResult
from ..core.hooks import emit
from ..services.vision import VisionService, VisionError

# (mode, regex) - first match wins
_MODES = [
    ("image",    r"\b(?:analy[sz]e|describe|read|inspect)\s+(?:this |the )?image\s+[\"']?(.+?\.(?:png|jpe?g|webp|bmp|gif))[\"']?\s*$"),
    ("copy_fix", r"\b(copy|put)\b.*\b(fix|fixed code|corrected code|solution)\b"),
    ("debug",    r"\bwhat'?s wrong with (my|this|the) (code|program|script)\b|\bwhat is wrong with (my|this|the) (code|program|script)\b"
                 r"|\b(wrong|bugs?|errors?|issues?|problems?|mistakes?|exceptions?|tracebacks?|not working|broken|failing|crash\w*)\b.*\b(code|program|script|function|screen|editor|terminal)\b"
                 r"|\b(code|program|script|function|screen|editor|terminal)\b.*\b(wrong|bugs?|errors?|issues?|mistakes?|exceptions?|tracebacks?|not working|broken|failing|crash\w*)\b"
                 r"|\b(fix|debug|find the (bug|error|mistake))\b.*\b(code|program|script|function)\b"
                 r"|\bwhy (is|does|isn'?t|won'?t|doesn'?t) (my|this|the) (code|program|script)\b"
                 r"|\bwhat does (this|that|the) (error|exception|traceback)\b"
                 r"|\b(explain|inspect|check)\b.*\b(error|bug|traceback|exception)s?\b"),
    ("study",    r"\bexplain (this|the) (question|problem)\b"),
    ("diagram",  r"\bexplain (this|the) (diagram|chart|graph|figure)\b"),
    ("summary",  r"\bsummari[sz]e (this|the|my) (page|screen|document|article)\b"),
    ("read",     r"\bread (my |the )?screen\b|\bread (this|the) text\b"),
    ("screen",   r"\b(look at|analy[sz]e|describe|inspect|check)\b.*\b(my |the )?screen\b|\bwhat('?s| is) on (my |the )?screen\b|\bwhat (do|can) you see\b|\bwhat am i looking at\b"),
    ("ask",      r"\b(on|in) (my|the|this) screen\b"),
]

_PROMPTS = {
    "screen":  "Describe what is on this computer screen: the main application, the important visible content, and anything that looks like a problem. At most 4 short sentences, plain text, no markdown.",
    "ask":     "Look at this computer screen and answer the user's request. Be specific and brief (at most 4 short sentences, plain text, no markdown).\nUser request: {q}",
    "read":    "Read the main visible text on this screen. Output only the text, in reading order.",
    "study":   "Read the visible question or problem and explain it to a beginner in at most 5 short sentences, plain text. If it can be solved quickly, give the answer.",
    "diagram": "Explain the visible diagram or chart to a beginner: what it shows, the main parts, and the key takeaway. At most 5 short sentences, plain text.",
    "summary": "Summarise the visible page or document in at most 5 short sentences, plain text, no markdown.",
}

_OCR_PROMPT = ("Transcribe, exactly as shown, any source code and any error message or traceback visible on this screen. "
               "Keep line numbers and indentation if visible. Output only the transcription, no commentary.")

_DEBUG_ONEPASS = ("You are a careful debugging assistant looking at the user's screen. Find the code and/or error message visible. "
                  "Explain the cause in at most 4 short plain sentences, then give the corrected code in ONE fenced code block. "
                  "If nothing is wrong or no code is visible, say so. If ambiguous, say so instead of claiming certainty. "
                  "Never invent code that is not visible.")

_DEBUG_SYSTEM = ("You are a careful debugging assistant. You are given text transcribed from the user's screen; "
                 "it may contain small reading mistakes. Identify the error (if any), explain the cause in plain words "
                 "in at most 4 short sentences, then give the corrected code in ONE fenced code block. "
                 "If the problem is ambiguous, say so instead of claiming certainty. Do not invent code that is not visible.")


def _speakable(text: str, limit: int = 380) -> tuple[str, bool]:
    """Strip code blocks and cut to a few sentences so TTS stays short."""
    had_code = "```" in text
    plain = re.sub(r"```.*?```", " ", text, flags=re.S)
    plain = re.sub(r"[*_`#>]+", "", plain)
    plain = re.sub(r"\s+", " ", plain).strip()
    sentences = re.split(r"(?<=[.!?])\s+", plain)
    out = ""
    for s in sentences:
        if len(out) + len(s) > limit and out:
            break
        out += (" " if out else "") + s
    return out, had_code


def _last_code_block(text: str):
    blocks = re.findall(r"```[\w+-]*\n?(.*?)```", text or "", flags=re.S)
    return blocks[-1].strip("\n") if blocks else None


class VisionSkill(Skill):
    name = "vision"
    priority = 5            # before everything else: these phrases are unambiguous

    def match(self, text):
        t = text.lower().strip()
        for mode, pattern in _MODES:
            m = re.search(pattern, t)
            if m and mode == "debug" and re.search(r"clipboard|\bcopied\b", t):
                continue                      # "fix the code in my clipboard" belongs to the clipboard skill
            if m:
                if mode == "screen" and re.search(r"\b(wrong|error|bug|issue|problem|fix)\b", t):
                    mode = "debug"
                return {"mode": mode, "q": t, "path": (m.group(1).strip().strip('\"\'') if mode == "image" else None)}
        return None

    def execute(self, args, assistant):
        mode = args["mode"]
        if mode == "image":
            path = args.get("path")
            if not path:
                assistant.speak(f"Tell me the image path, {assistant.user_name}.")
                return SkillResult(True, False, "missing image path", skill=self.name)
            if not hasattr(assistant, "vision"):
                assistant.vision = VisionService(assistant)
            try:
                full = assistant.vision.analyze_image_file(
                    path,
                    "Analyze this image carefully. Describe the important content and answer any obvious question about it. "
                    "Be concise and honest about uncertainty.",
                )
            except VisionError as exc:
                assistant.speak(str(exc))
                return SkillResult(True, False, str(exc), skill=self.name)
            assistant._last_full_text = full
            spoken, _ = _speakable(full)
            assistant.speak(spoken or "I couldn't make anything useful out of that image.")
            assistant._last_response = full
            return SkillResult(True, True, full, skill=self.name)
        if mode == "copy_fix":
            return self._copy_fix(assistant)
        if not hasattr(assistant, "vision"):
            assistant.vision = VisionService(assistant)
        v = assistant.vision
        who = assistant.user_name
        emit(assistant, "state", "ANALYZING")
        assistant.speak(("Let me take a look, " if mode != "debug" else "Inspecting your screen, ") + f"{who}.", wait=False)
        try:
            t0 = time.perf_counter()
            if mode == "debug":
                emit(assistant, "log", f"Screenshot captured -> {v.model} (vision)")
                if v.same_model:          # one pass: same model sees the image and reasons about it
                    full = v.look("What is wrong here and how do I fix it?", num_predict=650, max_width=1600,
                                  active_window=True, system=_DEBUG_ONEPASS)
                else:                     # small VLM reads, main model reasons
                    seen = v.look(_OCR_PROMPT, num_predict=450, max_width=1600, active_window=True)
                    if len(seen.strip()) < 15:
                        full = "I can't see any code or error on the screen right now."
                    else:
                        emit(assistant, "log", "Handing transcription to reasoning model")
                        emit(assistant, "state", "THINKING")
                        full = v.reason(_DEBUG_SYSTEM, f"Text from the user's screen:\n\n{seen}\n\nWhat is wrong and how do I fix it?")
            else:
                emit(assistant, "log", f"Screenshot captured -> {v.model} ({mode})")
                prompt = _PROMPTS[mode].format(q=args.get("q", "")) if mode == "ask" else _PROMPTS[mode]
                full = v.look(prompt, max_width=1600 if mode in ("read", "study", "summary") else 1280,
                              active_window=mode in ("read", "study", "summary"))
            emit(assistant, "action", f"Vision / {mode} / {time.perf_counter() - t0:.1f}s")
        except VisionError as exc:
            assistant.speak(f"{exc}", wait=True)
            return SkillResult(True, False, str(exc), skill=self.name)
        except Exception as exc:
            print(f"[Vision Error] {exc}")
            assistant.speak(f"I couldn't analyse the screen, {who}.")
            return SkillResult(True, False, str(exc), skill=self.name)

        if not full:
            full = "I looked, but I couldn't make anything out."
        spoken, had_code = _speakable(full)
        if had_code:
            spoken += f" The corrected code is on screen, {who}. Say copy the fix to copy it."
        assistant._last_full_text = full               # GUI shows the full answer
        assistant._last_code = _last_code_block(full) or getattr(assistant, "_last_code", None)
        assistant.speak(spoken)
        assistant._last_response = full                # so follow-up questions see the whole thing
        return SkillResult(True, True, full, skill=self.name)

    @staticmethod
    def _copy_fix(assistant):
        code = getattr(assistant, "_last_code", None)
        if not code:
            assistant.speak(f"I don't have any corrected code to copy yet, {assistant.user_name}.")
            return SkillResult(True, False, "no code", skill="vision")
        try:
            import pyperclip
            pyperclip.copy(code)
            assistant.speak(f"Copied the corrected code to your clipboard, {assistant.user_name}.")
            return SkillResult(True, True, "copied", skill="vision")
        except Exception:
            assistant.speak("I couldn't access the clipboard.")
            return SkillResult(True, False, "clipboard", skill="vision")
