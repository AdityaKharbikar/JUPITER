from .base import Skill, result_from_last_response
from ..common import NEW_CONV_PATTERN,NEW_CONV_WITH_SUMMARY_PATTERN,SWITCH_CONV_PATTERN,LIST_CONV_PATTERN,CONTINUE_PATTERN,SUMMARISE_PATTERN,RECALL_EARLIER_WORDS,RECALL_SPECIFIC_PATTERN,RECALL_PREVIOUS_PATTERN
class ConversationSkill(Skill):
    name="conversation"; priority=105
    def match(self,text):
        t=text.lower()
        if NEW_CONV_WITH_SUMMARY_PATTERN.search(t):return {"op":"new_summary"}
        if NEW_CONV_PATTERN.search(t):return {"op":"new"}
        m=SWITCH_CONV_PATTERN.search(t)
        if m:return {"op":"switch","id":int(m.group(1))}
        if LIST_CONV_PATTERN.search(t):return {"op":"list"}
        if CONTINUE_PATTERN.match(t):return {"op":"continue"}
        if SUMMARISE_PATTERN.search(t):return {"op":"summary"}
        if RECALL_SPECIFIC_PATTERN.search(t) or RECALL_PREVIOUS_PATTERN.search(t) or RECALL_EARLIER_WORDS.search(t):return None
        return None
    def execute(self,args,assistant):
        # For new conversation / summary paths, keep the original dispatcher as the exact behavior reference.
        assistant.handle_action(assistant._normalise_command(getattr(assistant,'_pending_router_command','')))
        return result_from_last_response(assistant,self.name)
