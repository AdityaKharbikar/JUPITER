import re

from .base import Skill, SkillResult
from ..core.hooks import emit
from ..services.workflow import WorkflowService, load_workflows, find_workflow

_VERB = re.compile(r"\b(start|activate|enable|launch|begin|run|enter|switch to|turn on|prepare for|prepare my|set up|initiate)\b")
_END = re.compile(r"\b(end|exit|stop|leave|finish|close|cancel|turn off|disable|quit)\b")
_END_GENERIC = re.compile(r"\b(?:end|exit|stop|leave|finish)\s+(?:the\s+|this\s+|my\s+|current\s+)?(?:mission|workflow|current mode|session)\b")
_LIST = re.compile(r"\b(list|what|which|show)\b.*\b(modes|workflows|missions)\b")


class WorkflowSkill(Skill):
    """Matches ONLY when the sentence names a workflow defined in data/workflows.json,
    so 'open chrome' or 'start a timer' still reach their normal skills."""
    name = "workflow"
    priority = 8

    def match(self, text):
        t = text.lower().strip()
        if _LIST.search(t):
            return {"op": "list"}
        # "end study mode", "exit coding mode", "stop focus session", "end the mission"
        if _END_GENERIC.search(t):
            return {"op": "end", "name": None}
        if _END.search(t):
            name = find_workflow(load_workflows(), t)
            if name:
                return {"op": "end", "name": name}
        if _VERB.search(t) or t.endswith(" mode"):
            name = find_workflow(load_workflows(), t)
            if name:
                return {"op": "run", "name": name}
        return None

    def execute(self, args, assistant):
        if args["op"] == "end":                      # needs no workflow service (and no data_dir)
            return self._end(args.get("name"), assistant)
        if not hasattr(assistant, "workflows"):
            assistant.workflows = WorkflowService(assistant)
        svc = assistant.workflows
        if args["op"] == "list":
            names = ", ".join(svc.names())
            assistant.speak(f"I can run: {names}, {assistant.user_name}.")
            return SkillResult(True, True, names, skill=self.name)
        svc.workflows = load_workflows(assistant.data_dir)      # pick up edits to the JSON live
        done, total = svc.run(args["name"])
        return SkillResult(True, done == total, f"{args['name']}: {done}/{total}", skill=self.name)

    def _end(self, name, assistant):
        who = assistant.user_name
        current = getattr(assistant, "current_mode", "normal")
        if current == "normal" or (name and name != current):
            label = name or "Nothing"
            assistant.speak(f"{label.capitalize()} isn't running right now, {who}." if name
                            else f"No mode or mission is running right now, {who}.")
            return SkillResult(True, True, "not running", skill=self.name)
        removed = 0
        lock, timers = getattr(assistant, "_timers_lock", None), getattr(assistant, "_timers", None)
        if lock is not None and timers is not None:
            with lock:                       # only timers this mission started - never your other timers
                keep = [t for t in timers if t.get("workflow") != current]
                removed = len(timers) - len(keep)
                timers[:] = keep
        assistant.current_mode = "normal"
        extra = " I also cancelled its timer." if removed else ""
        assistant.speak(f"{current.capitalize()} ended. Back to normal, {who}.{extra}")
        emit(assistant, "log", f"Mission ended: {current}")
        return SkillResult(True, True, f"{current} ended", skill=self.name)
