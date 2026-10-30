from .base import Skill, result_from_last_response
from ..common import PLAY_PATTERN,YOUTUBE_OPEN_PATTERN,YOUTUBE_SEARCH_PATTERN,YOUTUBE_ON_TAIL_PATTERN,youtube_query,EXPLORER_PATTERN,OPEN_APP_PATTERN,OPEN_FILE_PATTERN
class MediaSkill(Skill):
    name="media"; priority=40
    def match(self,text):
        t=text.strip()
        m=YOUTUBE_SEARCH_PATTERN.search(t)
        if m and youtube_query(m):return {"op":"youtube","query":youtube_query(m)}
        if YOUTUBE_OPEN_PATTERN.match(t):return {"op":"youtube","query":None}
        if EXPLORER_PATTERN.match(t):return {"op":"explorer"}
        m=OPEN_FILE_PATTERN.match(t)
        if m:return {"op":"path","path":m.group(1).strip()}
        m=PLAY_PATTERN.match(t)
        if m:
            # "play despacito on YouTube" -> the song is "despacito" (YouTube is where, not what)
            return {"op":"play","query":YOUTUBE_ON_TAIL_PATTERN.sub("",m.group(1)).strip() or m.group(1).strip()}
        m=OPEN_APP_PATTERN.match(t)
        if m:return {"op":"app","query":m.group(1).strip()}
        return None
    def execute(self,args,assistant):
        op=args["op"]
        # Media/app/file commands should not teach vocabulary from song titles,
        # executable names, file extensions or full Windows paths.
        assistant._skip_vocab = True
        if op=="youtube":assistant.open_youtube(args["query"])
        elif op=="explorer":assistant.open_file_explorer()
        elif op=="play":assistant.play_song(args["query"])
        elif op=="path":assistant.open_app("file " + args["path"])
        else:assistant.open_app(args["query"])
        return result_from_last_response(assistant,self.name)
