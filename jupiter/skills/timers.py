from .base import Skill, result_from_last_response
from ..common import TIMER_SET_PATTERN,TIMER_LIST_PATTERN,TIMER_CANCEL_PATTERN,STOPWATCH_START_PATTERN,STOPWATCH_READ_PATTERN
class TimerSkill(Skill):
    name="timers"; priority=25
    def match(self,text):
        t=text.lower()
        m=TIMER_SET_PATTERN.search(t)
        if m:return {"op":"set","phrase":m.group(1).strip()}
        if TIMER_LIST_PATTERN.search(t):return {"op":"list"}
        if TIMER_CANCEL_PATTERN.search(t):return {"op":"cancel"}
        if STOPWATCH_START_PATTERN.search(t):return {"op":"sw_start"}
        if STOPWATCH_READ_PATTERN.search(t):return {"op":"sw_read","stop":bool(t.startswith("stop"))}
        return None
    def execute(self,args,assistant):
        op=args["op"]
        if op=="set":assistant.set_timer(args["phrase"])
        elif op=="list":assistant.list_timers()
        elif op=="cancel":assistant.cancel_timers()
        elif op=="sw_start":assistant.start_stopwatch()
        else:assistant.read_stopwatch(args["stop"])
        return result_from_last_response(assistant,self.name)
