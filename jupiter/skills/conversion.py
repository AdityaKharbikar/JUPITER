from .base import Skill, result_from_last_response
from ..common import CONVERT_PATTERN


class ConversionSkill(Skill):
    name = "conversion"
    priority = 85

    def match(self, text):
        m = CONVERT_PATTERN.search(text.lower())
        if not m:
            return None
        return {"amount": m.group(1), "src": m.group(2), "dst": m.group(3)}

    def execute(self, args, assistant):
        # convert_units() already speaks its result. Calling speak() again on
        # its None return value was the source of the literal "JUPITER: None".
        assistant.convert_units(args["amount"], args["src"], args["dst"])
        return result_from_last_response(assistant, self.name)
