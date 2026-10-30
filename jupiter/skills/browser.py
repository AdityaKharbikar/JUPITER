from .base import Skill, result_from_last_response
from ..common import SEARCH_PATTERN
import webbrowser
class BrowserSkill(Skill):
    name="browser"; priority=75
    def match(self,text):
        m=SEARCH_PATTERN.search(text); return {"query":m.group(1).strip()} if m and m.group(1).strip() else None
    def execute(self,args,assistant):
        q=args["query"]; webbrowser.open(f"https://duckduckgo.com/html/?q={q.replace(' ','+')}"); assistant.speak(f"Searching for {q}, sir.")
        return result_from_last_response(assistant,self.name,{"query":q})
