from .base import Skill, result_from_last_response
from ..common import TIME_PATTERN,DATE_PATTERN,NEWS_PATTERN,SUN_PATTERN,MOON_PATTERN
from datetime import datetime
class InformationSkill(Skill):
    name="information"; priority=90
    def match(self,text):
        t=text.lower().strip()
        if TIME_PATTERN.match(t):return {"op":"time"}
        if DATE_PATTERN.match(t):return {"op":"date"}
        m=NEWS_PATTERN.search(t)
        if m:return {"op":"news","topic":(m.group(1) or '').strip() or None}
        m=SUN_PATTERN.search(t)
        if m:return {"op":"sun","which":m.group(1),"place":(m.group(2) or '').strip() or None}
        if MOON_PATTERN.search(t):return {"op":"moon"}
        return None
    def execute(self,args,assistant):
        op=args["op"]
        if op=="time":r=assistant._get_ist_time().strftime('%I:%M %p'); assistant.speak(f"It is {r}, sir.")
        elif op=="date":r=assistant._get_ist_time().strftime('%A, %d %B %Y'); assistant.speak(f"Today is {r}, sir.")
        elif op=="news":r=assistant.get_news(args["topic"])
        elif op=="sun":r=assistant.get_sun_times(args["which"],args["place"])
        else:r=assistant.get_moon_phase()
        return result_from_last_response(assistant,self.name,{"result":r})
