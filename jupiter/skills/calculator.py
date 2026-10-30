from .base import Skill, result_from_last_response
import re
from ..common import CALCULATE_WORD_PATTERN, CALCULATE_EXPR_PATTERN, SPOKEN_MATH_PATTERN

class CalculatorSkill(Skill):
    name = "calculator"
    priority = 10
    def match(self, text):
        t=text.strip().lower()
        expr_match = CALCULATE_EXPR_PATTERN.fullmatch(t)
        if expr_match:
            return {"expression": t}
        if CALCULATE_WORD_PATTERN.search(t):
            return {"expression": re.sub(r"^.*?calculate\s+", "", t, flags=re.I).strip()}
        m = SPOKEN_MATH_PATTERN.match(t)
        if m:
            expr = m.group(1).strip()
            math_hint = re.search(
                r"\d|\b(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|"
                r"eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|"
                r"eighteen|nineteen|twenty|thirty|forty|fifty|hundred|thousand|"
                r"plus|minus|times|multiplied|divided|over|squared|cubed|"
                r"sqrt|square root|percent|percentage)\b|[+*/^%()-]",
                expr,
            )
            if not math_hint:
                return None
            return {"expression": expr}
        return None
    def execute(self,args,assistant):
        try:
            value=assistant._safe_eval_math(args["expression"])
            assistant.speak(f"The answer is {value}")
            return result_from_last_response(assistant,self.name,{"value":value})
        except Exception:
            assistant.speak("I couldn't calculate that, sir.")
            return result_from_last_response(assistant,self.name,success=False)
