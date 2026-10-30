import re

from .base import Skill, SkillResult

_ADD = re.compile(r"^(?:please\s+)?(?:add|create|new)\s+(?:a\s+|another\s+)?(?:new\s+)?task\s*(?:to\s+|called\s+|named\s+|[:,])?\s*(.+)$"
                  r"|^(?:please\s+)?add\s+(.+?)\s+to\s+(?:my|the)\s+(?:tasks?|to[\s-]?do(?:\s+list)?|todo(?:\s+list)?)$")
_LIST = re.compile(r"\b(?:what(?:'s| is| are)|show|list|read|tell me)\b.*\b(?:my\s+)?(?:tasks|to[\s-]?do list|todo list|to[\s-]?dos)\b")
_DONE = re.compile(r"^(?:please\s+)?(?:complete|finish|finished|done with|mark)\s+(?:the\s+)?task\s+(.+?)(?:\s+(?:as\s+)?(?:done|complete|completed))?$"
                   r"|^(?:i\s+)?(?:finished|completed)\s+(?:the\s+)?task\s+(.+)$")


class TasksSkill(Skill):
    """Voice front-end for the existing tasks table (the briefing and the GUI memory panel read it)."""
    name = "tasks"
    priority = 12

    def match(self, text):
        t = text.lower().strip().strip(".!?, ")
        m = _DONE.match(t)
        if m:
            return {"op": "done", "what": (m.group(1) or m.group(2)).strip()}
        m = _ADD.match(t)
        if m:
            return {"op": "add", "title": (m.group(1) or m.group(2)).strip()}
        if _LIST.search(t):
            return {"op": "list"}
        return None

    def execute(self, args, assistant):
        who, op = assistant.user_name, args["op"]
        if op == "add":
            assistant.add_task(args["title"])
            assistant.speak(f"Task added, {who}: {args['title']}.")
            return SkillResult(True, True, "added", skill=self.name)
        rows = assistant.list_tasks()
        if op == "list":
            if not rows:
                assistant.speak(f"You have no open tasks, {who}.")
            else:
                titles = "; ".join(f"{i}. {r[2]}" for i, r in enumerate(rows[:5], 1))
                more = f" And {len(rows) - 5} more." if len(rows) > 5 else ""
                assistant.speak(f"You have {len(rows)} open task{'s' if len(rows) != 1 else ''}, {who}: {titles}.{more}")
            assistant._last_full_text = None
            return SkillResult(True, True, "list", skill=self.name)
        what = args["what"]
        hit = None
        if what.isdigit() and 1 <= int(what) <= len(rows):
            hit = rows[int(what) - 1]
        else:
            matches = [r for r in rows if what in str(r[2]).lower() or str(r[2]).lower() in what]
            if len(matches) == 1:
                hit = matches[0]
            elif len(matches) > 1:
                assistant.speak(f"More than one task matches, {who}. Say the task number instead.")
                return SkillResult(True, False, "ambiguous", skill=self.name)
        if hit is None:
            assistant.speak(f"I couldn't find an open task called {what}, {who}.")
            return SkillResult(True, False, "not found", skill=self.name)
        assistant.complete_task(hit[0])
        assistant.speak(f"Marked as done, {who}: {hit[2]}.")
        return SkillResult(True, True, "done", skill=self.name)
