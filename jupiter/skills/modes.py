from .base import Skill, result_from_last_response
from ..common import TEXT_MODE_PATTERN,VOICE_MODE_PATTERN,WHICH_MODE_PATTERN,STICKY_TEXT_PATTERN,AUTO_VOICE_PATTERN,SLEEP_MODE_PATTERN,PTT_MODE_PATTERN,ACTIVE_MODE_PATTERN
class ModeSkill(Skill):
    name="modes"; priority=110
    def match(self,text):
        t=text.lower().strip()
        if STICKY_TEXT_PATTERN.search(t):return {"op":"sticky_text"}
        if AUTO_VOICE_PATTERN.search(t):return {"op":"auto_voice"}
        if TEXT_MODE_PATTERN.search(t):return {"op":"text"}
        if VOICE_MODE_PATTERN.search(t):return {"op":"voice"}
        if WHICH_MODE_PATTERN.search(t):return {"op":"which"}
        if SLEEP_MODE_PATTERN.match(t):return {"op":"sleep"}
        if PTT_MODE_PATTERN.match(t):return {"op":"ptt"}
        if ACTIVE_MODE_PATTERN.match(t):return {"op":"active"}
        return None
    def execute(self,args,assistant):
        op=args["op"]
        if op=="text":assistant.set_input_mode("text")
        elif op=="voice":assistant.set_input_mode("voice")
        elif op=="sleep":assistant.enter_sleep_mode()
        elif op=="ptt":assistant.set_listen_mode('push_to_talk')
        elif op=="active":assistant.set_listen_mode('active')
        elif op=="sticky_text":assistant.auto_return_to_voice=False; assistant._save_setting('auto_return_to_voice','0'); assistant.set_input_mode('text')
        elif op=="auto_voice":assistant.auto_return_to_voice=True; assistant._save_setting('auto_return_to_voice','1'); assistant.set_input_mode('voice')
        else:assistant.speak(f"I am in {assistant.input_mode} mode, {assistant.user_name}.")
        return result_from_last_response(assistant,self.name)
