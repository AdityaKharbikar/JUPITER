import os
import re

from .base import Skill, SkillResult
from ..core import confirm
from ..core.hooks import emit
from ..services import coderunner

_RUN = re.compile(r"\b(run|test|execute)\b.*\b(fix|fixed code|corrected code|that code|the code|this code|it)\b")


class DeveloperSkill(Skill):
    """'Run the fix' -> shows the code, asks for confirmation, runs it in the sandbox, reports the output."""
    name = "developer"
    priority = 6

    def match(self, text):
        t = text.lower().strip()
        if _RUN.search(t) and not re.search(r"\b(timer|alarm|music|song|video)\b", t):
            return {}
        return None

    def execute(self, args, assistant):
        who = assistant.user_name
        code = getattr(assistant, "_last_code", None)
        if not code:
            assistant.speak(f"There's no code to run yet, {who}. Ask me to inspect your screen first.")
            return SkillResult(True, False, "no code", skill=self.name)
        ok, why = coderunner.scan(code)
        if not ok:
            assistant.speak(f"I won't run that, {who}, because {why}.")
            return SkillResult(True, False, why, skill=self.name)
        sandbox = os.path.join(assistant.data_dir, "sandbox")

        def do_run():
            emit(assistant, "state", "THINKING")
            emit(assistant, "log", "Running code in sandbox (10 s limit)")
            res = coderunner.run(code, sandbox)
            assistant._last_full_text = f"Output:\n{res['output']}"
            first = res["output"].splitlines()[0] if res["output"] else "no output"
            assistant.speak(("It ran successfully. " if res["ok"] else "It failed. ") + f"Output begins: {first[:160]}")
            assistant._last_response = assistant._last_full_text

        n = len(code.splitlines())
        assistant._last_full_text = f"About to run this {n}-line script in the sandbox folder (10 s limit):\n```python\n{code}\n```"
        confirm.propose(assistant, f"run the {n} line script in a sandbox", do_run,
                        prompt=f"I'm ready to run the {n} line script in a sandbox with a ten second limit. Say confirm, or cancel.")
        return SkillResult(True, True, assistant._last_full_text, skill=self.name)
