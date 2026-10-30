from .base import Skill, result_from_last_response
from ..common import REMIND_PATTERN, REMIND_IN_PATTERN, SHOW_REMINDERS_PATTERN, CLEAR_REMINDERS_PATTERN
class ReminderSkill(Skill):
    name="reminders"; priority=30
    def match(self,text):
        t=text.lower()
        m=REMIND_IN_PATTERN.search(t)
        if m: return {"op":"add_in","when":m.group(1).strip(),"task":m.group(2).strip()}
        m=REMIND_PATTERN.search(t)
        if m: return {"op":"add","task":m.group(1).strip()}
        if SHOW_REMINDERS_PATTERN.search(t): return {"op":"list"}
        if CLEAR_REMINDERS_PATTERN.search(t): return {"op":"clear"}
        return None
    def execute(self,args,assistant):
        op=args["op"]
        if op=="add": assistant.add_reminder(args["task"])
        elif op=="add_in": assistant.add_reminder(f"{args['task']} {args['when']}")
        elif op=="list": assistant.list_reminders()
        else: assistant.clear_reminders()
        return result_from_last_response(assistant,self.name)
