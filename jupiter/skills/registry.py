from ..core.skill import SkillResult
from .calculator import CalculatorSkill
from .weather import WeatherSkill
from .reminders import ReminderSkill
from .timers import TimerSkill
from .media import MediaSkill
from .browser import BrowserSkill
from .navigation import NavigationSkill
from .system import SystemSkill
from .documents import DocumentSkill
from .productivity import ProductivitySkill
from .conversion import ConversionSkill
from .information import InformationSkill
from .translation import TranslationSkill
from .memory import MemorySkill
from .modes import ModeSkill
from .greeting import GreetingSkill
from .vision import VisionSkill
from .workflow import WorkflowSkill
from .briefing import BriefingSkill
from .confirm import ConfirmSkill
from .developer import DeveloperSkill
from .clipboard_ai import ClipboardAISkill
from .health import HealthSkill
from .control import ControlSkill
from .tasks import TasksSkill
from .explainer import ExplainerSkill

# Free-text arguments get their original capitalisation back after a lowercase
# retry (notes, task titles, search words, places...). Control values such as
# "op", "direction", "lang" or a workflow "name" are never touched.
_TEXT_ARGS = ("text", "query", "task", "title", "question", "fact", "path", "folder", "place")


def _restore_case(args, original, lowered):
    if not isinstance(args, dict) or len(original) != len(lowered):
        return args
    fixed = dict(args)
    for key in _TEXT_ARGS:
        value = fixed.get(key)
        if isinstance(value, str) and value:
            i = lowered.find(value)
            if i >= 0:
                fixed[key] = original[i:i + len(value)]
    return fixed


class SkillRegistry:
    def __init__(self, skills=None):
        self.skills = sorted(skills or [], key=lambda s:s.priority)
    def route(self, text):
        # Speech-to-text and typing give "Search cats on YouTube" / "Open Notepad".
        # Many skill patterns are lowercase-only, so each skill gets a second try
        # on the lowercased text BEFORE the next skill is consulted - otherwise a
        # later, looser skill (plain web search, greeting...) wins just because of
        # a capital letter, e.g. "search lofi on YouTube" going to DuckDuckGo.
        lowered = text.lower()
        retry = lowered != text
        for skill in self.skills:
            args=skill.match(text)
            if args is None and retry:
                args=_restore_case(skill.match(lowered), text, lowered)
            if args is not None:
                return skill,args
        return None,None

def default_skills():
    return [ConfirmSkill(),ExplainerSkill(),HealthSkill(),BriefingSkill(),VisionSkill(),DeveloperSkill(),ClipboardAISkill(),WorkflowSkill(),ControlSkill(),TasksSkill(),CalculatorSkill(),TimerSkill(),ReminderSkill(),WeatherSkill(),MediaSkill(),BrowserSkill(),NavigationSkill(),SystemSkill(),DocumentSkill(),ProductivitySkill(),ConversionSkill(),InformationSkill(),TranslationSkill(),MemorySkill(),ModeSkill(),GreetingSkill()]
