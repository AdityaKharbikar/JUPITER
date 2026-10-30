from .base import Skill, result_from_last_response
from ..common import WEATHER_PATTERN
class WeatherSkill(Skill):
    name="weather"; priority=20
    def match(self,text):
        m=WEATHER_PATTERN.search(text.lower()); return {"place":(m.group(1) or "").strip() or None} if m else None
    def execute(self,args,assistant):
        # get_weather() speaks the response itself. Do not speak its None return.
        assistant.get_weather(args["place"])
        return result_from_last_response(assistant,self.name)
