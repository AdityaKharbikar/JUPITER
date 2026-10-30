from .base import Skill, result_from_last_response
from ..common import LOCATION_PATTERN
class NavigationSkill(Skill):
    name="navigation"; priority=50
    def match(self,text):
        m=LOCATION_PATTERN.search(text); return {"place":m.group(1).strip()} if m else None
    def execute(self,args,assistant):
        r=assistant.find_location(args["place"]); return result_from_last_response(assistant,self.name,{"result":r})
