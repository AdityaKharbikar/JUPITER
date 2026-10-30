from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
import subprocess


class Permission(IntEnum):
    SAFE = 0
    NORMAL = 1
    SENSITIVE = 2
    DANGEROUS = 3


@dataclass(frozen=True)
class ActionPolicy:
    name: str
    level: Permission
    confirmation_required: bool


DEFAULT_POLICIES = {
    "time": ActionPolicy("time", Permission.SAFE, False),
    "weather": ActionPolicy("weather", Permission.SAFE, False),
    "open_app": ActionPolicy("open_app", Permission.NORMAL, False),
    "delete_file": ActionPolicy("delete_file", Permission.SENSITIVE, True),
    "shell": ActionPolicy("shell", Permission.DANGEROUS, True),
}


class SecurityManager:
    """Safety boundary for future autonomous OS actions."""

    def __init__(self, allowed_roots=None, allowed_commands=None, max_runtime=15):
        self.allowed_roots = [Path(p).resolve() for p in (allowed_roots or [Path.home() / "Projects"])]
        self.allowed_commands = set(allowed_commands or {"python", "pip", "git"})
        self.max_runtime = max_runtime

    def policy(self, action: str) -> ActionPolicy:
        return DEFAULT_POLICIES.get(action, ActionPolicy(action, Permission.NORMAL, False))

    def requires_confirmation(self, action: str) -> bool:
        return self.policy(action).confirmation_required

    def is_path_allowed(self, path) -> bool:
        try:
            target = Path(path).resolve()
            return any(target == root or root in target.parents for root in self.allowed_roots)
        except OSError:
            return False

    def is_command_allowed(self, executable: str) -> bool:
        return executable.lower() in {x.lower() for x in self.allowed_commands}

    def run_allowed(self, executable: str, args=None):
        if not self.is_command_allowed(executable):
            raise PermissionError(f"Command is not allowlisted: {executable}")
        return subprocess.run(
            [executable, *(args or [])],
            timeout=self.max_runtime,
            capture_output=True,
            text=True,
            check=False,
        )
