from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

@dataclass
class SkillResult:
    handled: bool
    success: bool = True
    message: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    skill: str = ""

class Skill(ABC):
    name = "base"
    priority = 100

    @abstractmethod
    def match(self, text: str):
        """Return parsed arguments or None when this skill does not match."""
        raise NotImplementedError

    @abstractmethod
    def execute(self, args, assistant) -> SkillResult:
        """Execute a command against the composed JUPITER assistant."""
        raise NotImplementedError

def result_from_last_response(assistant, skill_name: str, data=None, success=True):
    return SkillResult(True, success, getattr(assistant, "_last_response", "") or "", data or {}, skill_name)
