from .base import Skill, result_from_last_response
from ..common import SYSTEM_STATS_PATTERN,WIFI_PATTERN,BATTERY_PATTERN,VOLUME_SET_PATTERN,VOLUME_UP_PATTERN,VOLUME_DOWN_PATTERN,VOLUME_MUTE_PATTERN,VOLUME_UNMUTE_PATTERN,REMEMBER_FACT_PATTERN,NOTE_ADD_PATTERN,REMIND_PATTERN


class SystemSkill(Skill):
    name = "system"
    priority = 60

    def match(self, text):
        t = text.lower().strip()
        # "remember that my wifi password is ..." / "note that the battery ..." are
        # statements to store, not requests for system info - let them reach the
        # memory / notes / reminder handlers instead of being hijacked here.
        if REMEMBER_FACT_PATTERN.match(t) or NOTE_ADD_PATTERN.search(t) or REMIND_PATTERN.search(t):
            return None
        if BATTERY_PATTERN.search(t):
            return {"op": "battery"}
        if SYSTEM_STATS_PATTERN.search(t):
            return {"op": "stats"}
        if WIFI_PATTERN.search(t):
            return {"op": "network"}
        m = VOLUME_SET_PATTERN.search(t)
        if m:
            return {"op": "volume", "level": int(m.group(1))}
        if VOLUME_UP_PATTERN.search(t):
            return {"op": "volume", "direction": "up"}
        if VOLUME_DOWN_PATTERN.search(t):
            return {"op": "volume", "direction": "down"}
        if VOLUME_MUTE_PATTERN.match(t):
            return {"op": "volume", "direction": "mute"}
        if VOLUME_UNMUTE_PATTERN.match(t):
            return {"op": "volume", "direction": "unmute"}
        return None

    def execute(self, args, assistant):
        op = args["op"]
        if op == "battery":
            assistant.get_battery_status()
        elif op == "stats":
            assistant.get_system_stats()
        elif op == "network":
            assistant.get_network_info()
        else:
            assistant.set_volume(args.get("direction"), args.get("level"))
        # The underlying service is responsible for speaking. Do not call
        # speak(str(return_value)) here: most service methods return None after
        # already producing the correct spoken answer.
        return result_from_last_response(assistant, self.name)
