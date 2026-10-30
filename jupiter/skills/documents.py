from .base import Skill, result_from_last_response
from ..common import DOC_INDEX_PATTERN,DOC_ASK_PATTERN,DOC_STATUS_PATTERN
class DocumentSkill(Skill):
    name="documents"; priority=70
    def match(self,text):
        t=text.lower()
        m=DOC_INDEX_PATTERN.search(t)
        if m:return {"op":"index","folder":(m.group(1) or "").strip() or None}
        m=DOC_ASK_PATTERN.search(t)
        if m:return {"op":"ask","question":(m.group(1) or m.group(2)).strip()}
        if DOC_STATUS_PATTERN.search(t):return {"op":"status"}
        return None
    def execute(self,args,assistant):
        op=args["op"]
        if op=="index":r=assistant.index_documents(args["folder"])
        elif op=="ask":r=assistant.ask_documents(args["question"])
        else:r=assistant.document_status()
        if r is not None and not getattr(assistant,'_last_response',None): assistant.speak(str(r))
        return result_from_last_response(assistant,self.name,{"result":r})
