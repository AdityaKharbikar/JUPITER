from .base import Skill, result_from_last_response
from ..common import TRANSLATE_PARSE_PATTERN
class TranslationSkill(Skill):
    name="translation"; priority=95
    def match(self,text):
        m=TRANSLATE_PARSE_PATTERN.search(text); return {"text":m.group(1).strip(),"lang":m.group(2).strip()} if m else None
    def execute(self,args,assistant):
        r=assistant.translate_text(args["text"],args["lang"]); assistant.speak(f"In {args['lang']}, that is: {r}"); return result_from_last_response(assistant,self.name,{"result":r})
