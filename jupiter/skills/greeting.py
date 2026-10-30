from .base import Skill, result_from_last_response
from ..common import GREETING_PATTERN, IDENTITY_PATTERN, GREETING_REPLIES, TIMED_GREETING_REPLIES
class GreetingSkill(Skill):
    name="greeting"; priority=120
    def match(self,text):
        t=text.strip().lower()
        if IDENTITY_PATTERN.search(t):return {"op":"identity"}
        if GREETING_PATTERN.search(t):return {"op":"greet","word":GREETING_PATTERN.search(t).group(1)}
        return None
    def execute(self,args,assistant):
        if args["op"]=="identity":assistant.speak(f"I am JUPITER, your local personal assistant, {assistant.user_name}.")
        else:assistant.speak(assistant._pick(TIMED_GREETING_REPLIES,greet=args['word'].capitalize()) if args['word'].startswith('good') else assistant._pick(GREETING_REPLIES))
        return result_from_last_response(assistant,self.name)
