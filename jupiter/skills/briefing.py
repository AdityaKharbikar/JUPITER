import re

from .base import Skill, SkillResult
from ..core.hooks import emit
from ..services.briefing import compose

_PAT = re.compile(r"\b(briefing|brief me|status report|daily report|morning report)\b|\bgive me (a |my )?(summary of my day|rundown)\b")


class BriefingSkill(Skill):
    name = "briefing"
    priority = 4

    def match(self, text):
        return {} if _PAT.search(text.lower()) else None

    def execute(self, args, assistant):
        emit(assistant, "log", "Reading battery, system, tasks, reminders, memory")
        text = compose(assistant)
        assistant._last_full_text = text
        assistant.speak(text)
        return SkillResult(True, True, text, skill=self.name)
