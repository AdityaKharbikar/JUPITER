import re

from .base import Skill, SkillResult
from ..core.health import HealthChecker

_PAT = re.compile(r"\b(?:health check|system health|diagnostics|run diagnostics|is everything okay|are you healthy)\b", re.I)


class HealthSkill(Skill):
    name = "health"
    priority = 3

    def match(self, text):
        return {} if _PAT.search(text) else None

    def execute(self, args, assistant):
        report = HealthChecker(assistant).report()
        assistant._last_full_text = report
        assistant.speak(report)
        return SkillResult(True, True, report, skill=self.name)
