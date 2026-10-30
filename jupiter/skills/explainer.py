"""Voice / typed commands for the 3D Explainer, webcam identification and the performance report."""
import re

from .base import Skill, SkillResult
from ..explainer import library
from ..explainer.service import ExplainerService

_VERB_TOPIC = [
    r"^(?:please )?(?:show|display|give|build|make|create|generate|draw)(?: me)?(?: an?| the)? (?:3d |exploded |exploded-view |interactive )*(?:model|view|visuali[sz]ation|diagram|animation)(?: of| for)? (.+)$",
    r"^(?:please )?(?:show|display|visuali[sz]e)(?: me)?(?: how)? (?:a |an |the )?(.+?) (?:works?|is assembled|are assembled|is built|are built|is put together)\??$",
    r"^(?:please )?(?:explain|tell me|describe)(?: to me)? how (?:a |an |the )?(.+?) (?:is|are) (?:assembled|built|put together)\??$",
    r"^(?:please )?(?:show|display|explain|give)(?: me)? (?:the )?(?:internal structure|internals|inside|parts|components|anatomy|layers|architecture|structure) (?:of|in) (?:a |an |the |my )?(.+)$",
    r"^(?:please )?(?:what are |list |explain )(?:the )?(?:parts|components|layers) (?:of|in) (?:a |an |the )?(.+)$",
    r"^(?:please )?(?:explode|visuali[sz]e|dissect|disassemble|take apart|break down)(?: me)? (?:the |a |an |my )?(.+)$",
    r"^(?:3d|explainer|exploded view|exploded)(?: view)?(?: of)? (.+)$",
    r"^how (?:is|are) (?:a |an |the )?(.+?) (?:assembled|built|made|put together)\??$",
]
# "explain how X works" is ordinary chat unless X is one of the curated models.
_CURATED_ONLY = [r"^(?:please )?(?:explain|tell me|describe)(?: to me)? how (?:a |an |the )?(.+?) works?\??$",
                 r"^how does (?:a |an |the )?(.+?) work\??$"]
_REGEN = re.compile(r"^(?:please )?(?:regenerate|rebuild|generate (?:a )?(?:new|fresh))(?: the)?(?: 3d)?(?: (?:model|view|visuali[sz]ation))?(?: of| for)? (.+)$")
_LOOSE = {5}   # indexes of _VERB_TOPIC patterns that are too generic to accept arbitrary topics
_NOT_TOPIC = re.compile(r"\b(screen|clipboard|code|error|page|file|image|document|conversation|my day|day|schedule|timer|reminder|window|tab|volume|brightness)\b")
_TAIL = re.compile(r"\b(please|in 3d|in detail|step by step|for me|in 3 d)\b|[?.!]+$")
_IT = re.compile(r"^(?:please )?(?:explode|open|show)(?: me)? (?:it|that|this|its (?:internal )?(?:components|parts|structure|insides?)|the (?:internal )?components|inside it)$"
                 r"|^show (?:me )?(?:its|the) (?:internal )?(?:components|parts|structure)$")
_LIST = re.compile(r"\b(?:what|which|list|show)\b.*\b(?:3d |exploded )?(?:models|topics|visuali[sz]ations)\b.*\b(?:have|can|available|know|support)?|\bwhat can you (?:show|visuali[sz]e|explode)\b")
_PERF = re.compile(r"\b(?:performance|benchmark|speed|metrics)\s+(?:report|summary|stats|statistics)\b|\bshow (?:the )?(?:performance|metrics)\b|\bhow fast (?:are|is) you\b")
_CAM = re.compile(r"\b(?:open|start|use|turn on|launch)\b.*\b(?:webcam|web cam|camera)\b|\b(?:what(?:'s| is)? (?:this|that) (?:object|thing|item)|identify (?:this|that|the) (?:object|thing|item)|what am i holding|look at this (?:object|thing)|recogni[sz]e this)\b")
_ONLINE = re.compile(r"^(?:please )?(?:find|search|look up|get) (?:more )?(?:info|information|details)(?: online| on the web)?(?: (?:about|on) (?:it|this|that))?$|^search (?:for )?(?:it|this object) online$")


# ---- 3D viewer control by voice. Only active after a model has been opened, so "reset" / "stop" etc. never hijack other skills. ----
_Z = r"(?:please )?(?:and )?"
_VIEW_CMDS = [   # (regex, command, argument)
    (r"(?:rotate|turn|spin)(?: it| the model)? (?:to the )?left", "rotate_left", 0.6), (r"(?:rotate|turn|spin)(?: it| the model)? (?:to the )?right", "rotate_right", 0.6),
    (r"(?:rotate|turn|tilt)(?: it| the model)? (?:up|upward|upwards)|look from below", "rotate_up", 0.4),
    (r"(?:rotate|turn|tilt)(?: it| the model)? (?:down|downward|downwards)|look from above|top view", "rotate_down", 0.4),
    (r"zoom in|(?:come |get |move )?closer|enlarge|magnify", "zoom_in", 0.7), (r"zoom out|(?:move |go |get )?(?:farther|further) away|shrink", "zoom_out", 0.7),
    (r"(?:pan|move)(?: it| the model)? left", "pan", [0.12, 0]), (r"(?:pan|move)(?: it| the model)? right", "pan", [-0.12, 0]),
    (r"(?:pan|move)(?: it| the model)? up", "pan", [0, 0.12]), (r"(?:pan|move)(?: it| the model)? down", "pan", [0, -0.12]),
    (r"(?:explode|expand|spread)(?: it| the model| the parts)?(?: out| apart)?|(?:take|pull) (?:it|the parts) apart", "explode", None),
    (r"(?:assemble|put (?:it )?together|collapse)(?: it| the model| the parts)?", "assemble", None),
    (r"(?:start|play|run|begin)(?: the)? (?:assembly|walkthrough|animation|tour)|assembly (?:mode|animation)", "play", None),
    (r"(?:stop|pause|halt)(?: the)? (?:assembly|walkthrough|animation|rotation|spinning|model|viewer)", "stop", None),
    (r"(?:turn |switch )?(?:on |off )?x[- ]?ray(?: mode| view)?(?: on| off)?", "xray", None),
    (r"(?:show|hide|toggle|turn on|turn off)(?: the)? labels?|labels? (?:on|off)", "labels", None),
    (r"isolate(?: mode| view)?(?: on| off)?|(?:turn |switch )(?:on |off )isolate", "isolate", None),
    (r"(?:auto[- ]?rotate|start rotating|keep rotating|rotate automatically)", "autorotate", True),
    (r"(?:reset|restore)(?: the)? (?:view|camera|model|position)", "reset", None),
    (r"(?:next|forward) part|next component", "next", None), (r"(?:previous|last|back) part|previous component", "prev", None),
    (r"(?:deselect|clear selection|unselect)", "deselect", None),
]
_VIEW_SELECT = re.compile(r"^(?:please )?(?:select|highlight|focus on|show me|point to|click|zoom to|what is|what does)(?: the)? (.+?)(?: part| component)?\??$")
_HAND_ON = re.compile(r"\b(?:enable|start|turn on|activate|switch on|use)\b.*\b(?:hand|gesture)s?\b(?: control| tracking| mode)?|\bhand (?:control|gestures?|tracking) on\b|\bcontrol (?:it |this )?with (?:my )?(?:hands?|gestures?)\b")
_HAND_OFF = re.compile(r"\b(?:disable|stop|turn off|deactivate|switch off)\b.*\b(?:hand|gesture)s?\b(?: control| tracking| mode)?|\bhand (?:control|gestures?|tracking) off\b")
_HELP = re.compile(r"\b(?:what|which|list|show|tell)\b.*\b(?:voice|hand|gesture|viewer|3d)\b.*\b(?:commands?|gestures?|controls?)\b|\bhow (?:do i|can i|to) control (?:the )?(?:3d|model|viewer)\b")
HELP_TEXT = """3D VIEWER - VOICE COMMANDS (say them after a model is open)
Rotate: "rotate left / right / up / down", "auto rotate", "top view"
Zoom: "zoom in", "zoom out", "closer", "further away"      Move: "pan left / right / up / down"
Explode: "explode", "assemble" (or "put it together")       Tour: "start assembly", "stop"
Display: "x-ray", "show labels", "hide labels", "isolate"   View: "reset view"
Parts: "select <part name>" (e.g. "select piston"), "next part", "previous part", "deselect"
Hands: "enable hand control" / "disable hand control"

HAND GESTURES (webcam, hand control ON; mirror view)
Open palm + move = rotate | Fist + move = pan | Two hands apart / together = zoom in / out
Index finger = pointer (hover) | Pinch thumb+index = click / select part
Peace sign (hold 1s) = explode / assemble | Thumbs up (hold) = x-ray | Call-me sign (thumb+pinky, hold) = labels
Three fingers (hold) = play assembly | Open palm held still 1.5s = stop"""


def _view_match(t):
    t = re.sub(r"^(?:jupiter[, ]+)?(?:please )?", "", t).strip(" .!")
    if _HAND_OFF.search(t):
        return {"mode": "view", "cmd": "hand_off", "arg": None}
    if _HAND_ON.search(t):
        return {"mode": "view", "cmd": "hand_on", "arg": None}
    for rx, c, arg in _VIEW_CMDS:
        if re.fullmatch(_Z + rx + r"(?: please)?", t):
            if c in ("xray", "labels", "isolate"):
                arg = False if re.search(r"\b(?:off|hide)\b", t) else (True if re.search(r"\b(?:on|show)\b", t) else None)
            return {"mode": "view", "cmd": c, "arg": arg}
    m = _VIEW_SELECT.match(t)
    if m and _service_mod().VIEW_PARTS:
        q = m.group(1).strip()
        if any(q == n or q in n or n in q for n in _service_mod().VIEW_PARTS):
            return {"mode": "view", "cmd": "select", "arg": q}
    return None


def _service_mod():
    from ..explainer import service as _svc
    return _svc


def _viewer_active():
    from ..explainer import service as _svc
    return _svc.VIEW_ACTIVE


def _clean(topic):
    topic = re.split(r"\s+(?:and|then|&)\s+(?:explain|show|label|describe|tell|name|list)\b", topic.lower())[0]
    t = _TAIL.sub("", topic).strip(" ,")
    t = re.sub(r"^(?:a |an |the |my )", "", t)
    return t.strip()


class ExplainerSkill(Skill):
    name = "explainer"
    priority = 4

    def match(self, text):
        t = re.sub(r"\s+", " ", text.lower().strip())
        if _HELP.search(t):
            return {"mode": "viewhelp"}
        if _viewer_active():
            v = _view_match(t)
            if v:
                return v
        if _PERF.search(t):
            return {"mode": "perf"}
        m = _REGEN.match(t)
        if m and _clean(m.group(1)) and not _NOT_TOPIC.search(m.group(1)) and library.find(_clean(m.group(1))):
            return {"mode": "explain", "topic": _clean(m.group(1)), "force_new": True}
        if _ONLINE.match(t):
            return {"mode": "online"}
        if _CAM.search(t):
            return {"mode": "camera"}
        if _IT.match(t):
            return {"mode": "again"}
        if _LIST.search(t) and re.search(r"\b3d\b|exploded|built-in|visuali|what can you show", t):
            return {"mode": "list"}
        for i, pat in enumerate(_VERB_TOPIC):
            m = re.match(pat, t)
            if m:
                topic = _clean(m.group(1))
                if topic and len(topic.split()) <= 8 and not _NOT_TOPIC.search(m.group(1)) \
                        and not re.match(r"(?:this|that|these|those|it)\b", topic) \
                        and (i not in _LOOSE or library.find(topic)):
                    return {"mode": "explain", "topic": topic}
        for pat in _CURATED_ONLY:
            m = re.match(pat, t)
            if m:
                topic = _clean(m.group(1))
                if topic and library.find(topic):
                    return {"mode": "explain", "topic": topic}
        return None

    @staticmethod
    def service(assistant) -> ExplainerService:
        svc = getattr(assistant, "explainer", None)
        if svc is None:
            svc = assistant.explainer = ExplainerService(assistant)
        return svc

    def execute(self, args, assistant):
        svc = self.service(assistant)
        who = getattr(assistant, "user_name", "sir")
        mode = args["mode"]
        if mode == "explain":
            res = svc.explain(args["topic"], force_new=args.get("force_new", False))
            return SkillResult(True, res.ok, res.error or res.title, {"source": res.source, "seconds": res.seconds}, self.name)
        if mode == "again":
            if not svc.last_topic:
                assistant.speak(f"There's nothing on screen to explode yet, {who}. Ask me for a topic or use the webcam first.")
                return SkillResult(True, False, "no topic", skill=self.name)
            res = svc.explain(svc.last_topic)
            return SkillResult(True, res.ok, res.title, skill=self.name)
        if mode == "viewhelp":
            assistant._last_full_text = HELP_TEXT
            assistant.speak("You can rotate, zoom, pan, explode, assemble, select parts, turn on x-ray or labels, and enable hand control. "
                            "I've put the full list of voice commands and hand gestures in the chat.")
            return SkillResult(True, True, "help", skill=self.name)
        if mode == "view":
            return self._view(args, assistant, svc, who)
        if mode == "list":
            topics = svc.engine.curated_topics()
            assistant.speak(f"I have {len(topics)} built-in models: {', '.join(topics)}. For anything else I can generate an approximate one with my language model.")
            assistant._last_full_text = "Built-in 3D models:\n- " + "\n- ".join(topics)
            return SkillResult(True, True, "list", skill=self.name)
        if mode == "perf":
            table = svc.metrics.report_markdown()
            assistant._last_full_text = "Measured on this machine:\n\n" + table
            assistant.speak(svc.metrics.spoken_summary())
            return SkillResult(True, True, table, skill=self.name)
        if mode == "online":
            if not svc.last_topic:
                assistant.speak(f"Tell me what to look up, {who}.")
                return SkillResult(True, False, "no topic", skill=self.name)
            svc.search_online(svc.last_topic)
            assistant.speak(f"Searching the web for {svc.last_topic}, {who}.")
            return SkillResult(True, True, "online", skill=self.name)
        if mode == "camera":
            if getattr(assistant, "ui_hook", None):
                from ..core.hooks import emit
                emit(assistant, "camera", "")
                assistant.speak(f"Camera panel opened, {who}. Press Capture when the object is in view.")
                return SkillResult(True, True, "camera panel", skill=self.name)
            info = svc.identify_console()
            return SkillResult(True, bool(info and info["object"] != "unknown"), "camera", skill=self.name)
        return None

    def _view(self, args, assistant, svc, who):
        from ..core.hooks import emit
        import json
        if getattr(assistant, "ui_hook", None) is None:
            assistant.speak(f"Viewer control works in the desktop window, {who}. In your browser use the mouse and the keys on screen.")
            return SkillResult(True, False, "console", skill=self.name)
        c, arg = args["cmd"], args.get("arg")
        emit(assistant, "viewer_cmd", f"{c}|{json.dumps(arg)}")
        say = {"hand_on": "Hand control on. Show me your open palm to rotate.", "hand_off": "Hand control off.",
               "select": f"Selecting {arg}."}.get(c)
        if say:
            assistant.speak(say, wait=False)
        return SkillResult(True, True, c, skill=self.name)
