from dataclasses import dataclass
from typing import Any

from ..skills.registry import SkillRegistry, default_skills


@dataclass
class RouteResult:
    handled: bool
    skill_name: str | None = None
    args: dict[str, Any] | None = None
    used_legacy_fallback: bool = False


class HybridRouter:
    """Deterministic skill routing first; legacy dispatcher second during migration."""

    def __init__(self, assistant, skills=None):
        self.assistant = assistant
        self.registry = SkillRegistry(skills or default_skills())

    def route(self, text: str) -> tuple[object | None, dict | None]:
        return self.registry.route(text)

    def dispatch(self, text: str) -> RouteResult:
        skill, args = self.registry.route(text)
        if skill is not None:
            result = skill.execute(args, self.assistant)
            return RouteResult(
                handled=bool(result.handled) if result is not None else True,
                skill_name=skill.name,
                args=args,
            )

        return RouteResult(
            handled=bool(self.assistant.handle_action(text)),
            used_legacy_fallback=True,
        )
