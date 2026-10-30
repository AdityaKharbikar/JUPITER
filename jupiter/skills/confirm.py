from .base import Skill, SkillResult
from ..core import confirm


class ConfirmSkill(Skill):
    """Only matches while something is waiting for a yes/no, so a stray 'no' or 'yes' never hijacks normal chat."""
    name = "confirm"
    priority = 1

    def match(self, text):
        if confirm.current() is None:
            return None
        t = text.lower().strip().strip(".!?, ")
        if confirm.YES.match(t):
            return {"yes": True}
        if confirm.NO.match(t):
            return {"yes": False}
        return None

    def execute(self, args, assistant):
        confirm.answer(assistant, args["yes"])
        return SkillResult(True, True, "", skill=self.name)
