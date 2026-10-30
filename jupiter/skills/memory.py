from .base import Skill, result_from_last_response
from ..common import REMEMBER_FACT_PATTERN,RECALL_FACTS_PATTERN,FORGET_FACTS_PATTERN
class MemorySkill(Skill):
    name="memory"; priority=100
    def match(self,text):
        m=REMEMBER_FACT_PATTERN.match(text)
        if m:return {"op":"remember","fact":m.group(1).strip()}
        if RECALL_FACTS_PATTERN.search(text):return {"op":"recall"}
        if FORGET_FACTS_PATTERN.search(text):return {"op":"forget"}
        return None
    def execute(self,args,assistant):
        op=args["op"]
        if op=="remember":assistant.remember_fact(args["fact"])
        elif op=="recall":assistant.recall_facts()
        else:assistant.forget_facts()
        return result_from_last_response(assistant,self.name)
