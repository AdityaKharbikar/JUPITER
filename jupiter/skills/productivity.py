from .base import Skill, result_from_last_response
from ..common import NOTE_ADD_PATTERN,NOTE_READ_PATTERN,NOTE_CLEAR_PATTERN,CLIPBOARD_READ_PATTERN,CLIPBOARD_SUMMARISE_PATTERN,CLIPBOARD_COPY_PATTERN,HISTORY_STATS_PATTERN
class ProductivitySkill(Skill):
    name="productivity"; priority=80
    def match(self,text):
        t=text.lower()
        m=NOTE_ADD_PATTERN.search(t)
        if m:return {"op":"note_add","text":m.group(1).strip()}
        if NOTE_READ_PATTERN.search(t):return {"op":"note_read"}
        if NOTE_CLEAR_PATTERN.search(t):return {"op":"note_clear"}
        if CLIPBOARD_READ_PATTERN.search(t):return {"op":"clip_read"}
        if CLIPBOARD_SUMMARISE_PATTERN.search(t):return {"op":"clip_sum"}
        if CLIPBOARD_COPY_PATTERN.search(t):return {"op":"clip_copy"}
        if HISTORY_STATS_PATTERN.search(t):return {"op":"usage"}
        return None
    def execute(self,args,assistant):
        op=args["op"]
        if op=="note_add":assistant.add_note(args["text"])
        elif op=="note_read":assistant.read_notes()
        elif op=="note_clear":assistant.clear_notes()
        elif op=="clip_read":assistant.read_clipboard()
        elif op=="clip_sum":assistant.summarise_clipboard()
        elif op=="clip_copy":assistant.copy_last_response()
        else:assistant.show_usage_stats()
        return result_from_last_response(assistant,self.name)
