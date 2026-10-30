#!/usr/bin/env python3
"""
JUPITER - Personal AI Assistant
Standard Version: Ollama + Whisper + Piper + Argos Translate
"""

import os
import json
import time
import subprocess
import sqlite3
import requests
import wave
import sys
import webbrowser
import ast
import operator
import shutil
import math
import threading
import queue
import struct
import glob
import io
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import re
import difflib
import random
from urllib.parse import quote_plus

# PortAudio is happier if two streams are never opened at the same instant
# (the speaker, the mic, and the "stop" listener can all open one).
_AUDIO_OPEN_LOCK = threading.Lock()

# One place to change the chat model. Override without editing code by setting
# the JUPITER_MODEL environment variable, e.g. (PowerShell):
#   $env:JUPITER_MODEL = "huihui_ai/qwen3.5-abliterated:4b"
# The abliterated tag needs Ollama v0.17.7 or newer.
LLM_MODEL = os.environ.get("JUPITER_MODEL", "qwen3.5:4b")

# Voice-activity detection (Silero, bundled with faster-whisper). Used to decide
# when you have STOPPED speaking, instead of plain loudness, so fans / TV hum
# neither keep the recorder open nor cut you off. Falls back to the old
# loudness check if it can't be imported.
try:
    from faster_whisper.vad import get_speech_timestamps as _fw_speech_ts
    from faster_whisper.vad import VadOptions as _FWVadOptions
    vad_available = True
except Exception:
    vad_available = False

if sys.platform == "win32":
    import winsound

# On Windows, faster-whisper's CUDA backend (CTranslate2) needs cuBLAS/cuDNN
# DLLs that don't ship with the GPU driver. If the standalone nvidia-cublas-cu12
# / nvidia-cudnn-cu12 pip packages are installed, point Windows at their DLLs.
PROJECT_ROOT = os.path.dirname(os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir)))

if sys.platform == "win32":
    # Two places we look for cuBLAS / cuDNN, in this order:
    #   1. C:\JUPITER\cuda_libs  (drop cublas64_12.dll, cublasLt64_12.dll and the
    #      cudnn*64_9.dll files here if you prefer not to use pip packages)
    #   2. the NVIDIA pip packages:  pip install nvidia-cublas-cu12 "nvidia-cudnn-cu12==9.*"
    # Each folder is registered with add_dll_directory AND put on PATH, because
    # native libraries sometimes ignore add_dll_directory on its own.
    _dll_dirs = [os.path.join(PROJECT_ROOT, "cuda_libs")]
    try:
        import nvidia.cublas
        import nvidia.cudnn
        for _pkg in (nvidia.cublas, nvidia.cudnn):
            _dll_dirs.append(os.path.join(list(_pkg.__path__)[0], "bin"))
    except Exception:
        pass
    for _d in _dll_dirs:
        if os.path.isdir(_d):
            try:
                os.add_dll_directory(_d)
            except Exception:
                pass
            os.environ["PATH"] = _d + os.pathsep + os.environ.get("PATH", "")

# Optional imports (with fallbacks)
try:
    from faster_whisper import WhisperModel
    whisper_available = True
except ImportError:
    whisper_available = False

try:
    import sounddevice as sd
    import numpy as np
    audio_input_available = True
except Exception:
    # NOT just ImportError: sounddevice raises OSError("PortAudio library not
    # found") at import time on machines without the native library, which
    # would otherwise crash Jupiter before it ever starts.
    audio_input_available = False

try:
    from piper import PiperVoice, SynthesisConfig
    piper_available = True
except Exception:
    piper_available = False

# Argos Translate is optional. It is intentionally NOT imported at startup because
# recent Argos versions depend on native SpaCy/Stanza extensions; on some Windows
# systems Smart App Control can block their unsigned .pyd files. Translation is
# loaded only when the user actually requests it.
translate_available = False

try:
    import pywhatkit
    pywhatkit_available = True
except ImportError:
    pywhatkit_available = False

try:
    import psutil
    psutil_available = True
except Exception:
    psutil_available = False

# Optional: clipboard read/write. Purely in-memory OS clipboard access —
# touches no files and changes no settings.
try:
    import pyperclip
    pyperclip_available = True
except Exception:
    pyperclip_available = False

# Optional: natural-language date parsing for reminders ("tomorrow at 6pm").
# Jupiter has a built-in fallback parser, so this is a nice-to-have, not a
# requirement — see _parse_when().
try:
    import dateparser
    dateparser_available = True
except Exception:
    dateparser_available = False

try:
    from ctypes import cast, POINTER
    from comtypes import CLSCTX_ALL
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
    volume_control_available = True
except Exception:
    volume_control_available = False

# Optional: a real offline English dictionary (pure Python, no compiler, no
# internet after install) so the vocabulary-learning feature stops flagging
# ordinary words ("reporter", "internet", ...) just because they're missing
# from the small hand-typed BASE_LEXICON below. Falls back to BASE_LEXICON
# alone if this isn't installed — nothing breaks, it's just less accurate.
try:
    from spellchecker import SpellChecker
    _spell = SpellChecker()
    spellchecker_available = True
except Exception:
    spellchecker_available = False


# --------------------------------------------------------------
#  INTENT PATTERNS
#  Compiled once at import time (not per-command) and matched with
#  word boundaries (\b) so "timer"/"sometimes" don't fire the time
#  handler, "hi" without a trailing space still greets, etc.
# --------------------------------------------------------------
## '.' (not a literal straight apostrophe) stands in for the apostrophe in
# "what's"/"today's", the same way YES_PATTERN/NO_PATTERN do for "don't"
# elsewhere in this file — so a typographic apostrophe (') from Whisper or a
# phone keyboard still matches instead of silently missing.
TIME_PATTERN = re.compile(r"^(?:time|what(?:.s| is)\s+(?:the\s+)?time|what\s+time\s+is\s+it|tell\s+me(?:\s+the)?\s+time|current\s+time|what\s+is\s+the\s+time\s+right\s+now)(?:[.!?])?$", re.IGNORECASE)
DATE_PATTERN = re.compile(r"^(?:date|what(?:'s| is)\s+(?:the\s+)?(?:date|today(?:'s)?\s+date)|what\s+day\s+is\s+it|tell\s+me(?:\s+today(?:'s)?|\s+the)?\s+date|today(?:'s)?\s+date|today\s+date)(?:[.!?])?$", re.IGNORECASE)
GREETING_PATTERN = re.compile(r'\b(hello|hi|hey|good morning|good evening|good afternoon)\b')
IDENTITY_PATTERN = re.compile(r'\bwho are you\b')
CALCULATE_WORD_PATTERN = re.compile(r'\bcalculate\b')
CALCULATE_EXPR_PATTERN = re.compile(r'^[\d\s\+\-\*\/\(\)\.]+$')
SEARCH_PATTERN = re.compile(r'\b(?:search for|look up|google|find|search)\b\s*(.*)')
TRANSLATE_TRIGGER_PATTERN = re.compile(r'\btranslate\b')
TRANSLATE_PARSE_PATTERN = re.compile(r'translate\s+(.+?)\s+to\s+(\w+)')
NEW_CONV_PATTERN = re.compile(r'\bnew conversation\b')
NEW_CONV_WITH_SUMMARY_PATTERN = re.compile(r'\bnew conversation\b.*\bsummary\b')
RECALL_PREVIOUS_PATTERN = re.compile(
    r'\b(previous|last|earlier)\s+conversation\b.*\bsummary\b'
    r'|\bsummary\b.*\b(previous|last|earlier)\s+conversation\b'
)
RECALL_SPECIFIC_PATTERN = re.compile(
    r'\bsummary\b.*\b(?:conversation|convo)\b\s*#?\s*(\d+)'
    r'|\b(?:conversation|convo)\b\s*#?\s*(\d+).*\bsummary\b'
)
SWITCH_CONV_PATTERN = re.compile(r'\bswitch\b.*\bconversation\b.*?(\d+)')
LIST_CONV_PATTERN = re.compile(r'\blist conversations\b')
CONTINUE_PATTERN = re.compile(r'^continue(\s+conversation)?$')
SUMMARISE_PATTERN = re.compile(r'\bsummar(?:is|iz)e\b')
REMIND_PATTERN = re.compile(r'\bremind me to\b\s*(.+)')
# Handles the "remind me in 20 minutes to call Mom" phrasing, where the
# duration comes before the task instead of after it. REMIND_PATTERN alone
# never matches this (no "remind me to" substring), so it used to fall
# through to the LLM.
REMIND_IN_PATTERN = re.compile(r'\bremind me\b\s+(in\s+.+?)\s+to\s+(.+)')
SHOW_REMINDERS_PATTERN = re.compile(r'\b(what are my reminders|show reminders|list reminders)\b')
CLEAR_REMINDERS_PATTERN = re.compile(r'\b(clear|delete)\b.*\breminders\b')
OPEN_FILE_PATTERN = re.compile(r'^open\b[,.]?\s+file\s+(.+)$')
SHUTDOWN_PATTERN = re.compile(
    r'^(?:(?:ok|okay|alright|all right|right|hey|please)[,\s]+)*'
    r'(?:jupiter[,\s]+)?'
    r'(?:quit|exit|goodbye|good\s*bye|bye[\s-]*bye|good\s*night|see\s+you(?:\s+(?:later|tomorrow|soon))?'
    r'|shut\s*down|power\s+off|sign\s+off|take\s+care|catch\s+you\s+later'
    r'|(?:close|quit|exit|shut\s*down)\s+(?:the\s+)?(?:jupiter|assistant|app|program))'
    r'(?:[,\s]+(?:jupiter|please|now))*[.!?\s]*$',
    re.IGNORECASE
)
# Spoken interrupt: say one of these WHILE Jupiter is talking and it stops
# mid-sentence and goes straight back to listening. It is matched against the
# last 1-3 words of a short clip (see Jupiter._is_interrupt_phrase), so it still
# works when a little of Jupiter's own voice leaks into the same clip. It is
# deliberately NOT part of SHUTDOWN_PATTERN - saying "stop" never quits Jupiter.
INTERRUPT_PATTERN = re.compile(
    r"^(?:(?:ok|okay|hey|please|jupiter)[\s,]+)*"
    r"(?:stop(?:\s+(?:it|that|talking|speaking|now|please))?|enough|that.?s\s+enough|be\s+quiet|quiet|shut\s+up)"
    r"(?:[\s,]+(?:jupiter|please|now))*[.!?\s]*$",
    re.IGNORECASE,
)

# Tidying applied to what Whisper heard BEFORE the (anchored) command patterns
# see it - see Jupiter._normalise_command. "um, could you please open notepad
# for me" should behave exactly like "open notepad".
FILLER_LEAD_PATTERN = re.compile(
    r"^(?:(?:uh+|um+|er+|erm|ah+|hmm+|so|well|okay|ok|alright|now|then|and)\b[,\s]*)+",
    re.IGNORECASE,
)
POLITE_LEAD_PATTERN = re.compile(
    r"^(?:(?:please|kindly)\b[,\s]*"
    r"|(?:can|could|would|will)\s+you\s+(?:please\s+)?"
    r"|i\s+(?:want|need)\s+you\s+to\s+"
    r"|i(?:\s+would|.d)\s+like\s+you\s+to\s+"
    r"|go\s+ahead\s+and\s+)+",
    re.IGNORECASE,
)
POLITE_TAIL_PATTERN = re.compile(
    r"(?:[,\s]+(?:please|thanks|thank\s+you|for\s+me))+[.!?\s]*$",
    re.IGNORECASE,
)
SPOKEN_MATH_PATTERN = re.compile(
    r"^(?:what(?:.s| is)|how\s+much\s+is|calculate|compute)\s+(.+?)[?.!\s]*$",
    re.IGNORECASE,
)
CALL_ME_PATTERN = re.compile(r'\bcall me\b\s+(.+)')
TEACH_WORD_PATTERN = re.compile(
    r'\bremember\s+the\s+word\s+(.+?)\s*$'
    r'|\bteach\s+you\s+the\s+word\s+(.+?)\s*$'
    r'|\badd\s+(.+?)\s+to\s+(?:my\s+|your\s+)?vocabulary\s*$',
    re.IGNORECASE
)

# --- New: media / apps / navigation patterns -------------------------------
# Order matters in handle_action(): more specific patterns (YouTube search,
# "open explorer", "open youtube") must be checked before the generic
# SEARCH_PATTERN and OPEN_APP_PATTERN so they aren't swallowed by them.
_YT = r'you\s?tube'          # "youtube", "YouTube", "You Tube" (speech-to-text often splits it)
YOUTUBE_SEARCH_PATTERN = re.compile(
    rf'(?:search|look\s+up|find)\s+(?:for\s+)?(.+?)\s+(?:on|in|at)\s+{_YT}\b'     # search lofi on YouTube
    rf'|(?:search|look\s+up|find)\s+{_YT}\s+for\s+(.+)'                          # search YouTube for lofi
    rf'|\b{_YT}\s+search\s+(?:for\s+)?(.+)',                                       # YouTube search lofi
    re.IGNORECASE)
YOUTUBE_ON_TAIL_PATTERN = re.compile(rf'\s+(?:on|in|at)\s+{_YT}[.!?\s]*$', re.IGNORECASE)


def youtube_query(match) -> str:
    """The search words from YOUTUBE_SEARCH_PATTERN (whichever phrasing matched)."""
    return next((g.strip() for g in match.groups() if g and g.strip()), "")


YOUTUBE_OPEN_PATTERN = re.compile(rf'^open\b[,.]?\s+{_YT}[.!?\s]*$', re.IGNORECASE)
EXPLORER_PATTERN = re.compile(r'^open\b[,.]?\s+(?:file explorer|explorer|files)$')
# STT commonly inserts a comma right after a leading imperative verb
# ("Play, high on you", "Open, notepad") — the old '^play\s+' required
# whitespace to be the VERY NEXT character, so that comma silently broke the
# match on every such utterance and sent the whole command to the LLM
# instead, which then improvised a fake response instead of actually playing
# anything. [,.]? absorbs that punctuation before requiring the real gap.
PLAY_PATTERN = re.compile(r'^play\b[,.]?\s+(.+)$')
LOCATION_PATTERN = re.compile(
    r'\b(?:where is|locate|find location of|navigate to|directions to|show me the way to)\b\s+(.+)'
)
OPEN_APP_PATTERN = re.compile(r'^open\b[,.]?\s+(.+)$')  # generic fallback — keep last among "open" checks

WEATHER_PATTERN = re.compile(r'\b(?:weather|temperature)\b(?:\s+(?:in|at|for)\s+(.+))?')
BATTERY_PATTERN = re.compile(r'\bbattery\b')
VOLUME_SET_PATTERN = re.compile(r'\bset volume to\s+(\d{1,3})\b')
VOLUME_UP_PATTERN = re.compile(r'\b(?:volume up|increase volume|turn up the volume)\b')
VOLUME_DOWN_PATTERN = re.compile(r'\b(?:volume down|decrease volume|turn down the volume)\b')
VOLUME_MUTE_PATTERN = re.compile(r'^mute$')
VOLUME_UNMUTE_PATTERN = re.compile(r'^unmute$')
LANG_MODE_PATTERN = re.compile(r'\b(english|hindi|marathi)\s+mode\b|\bswitch\s+to\s+(english|hindi|marathi)\b')

# --- New: input mode (voice <-> text) --------------------------------------
# Checked BEFORE LANG_MODE_PATTERN in handle_action so "text mode" can never be
# mistaken for a language switch. Works spoken or typed, so you can always get
# back out of whichever mode you're stuck in.
TEXT_MODE_PATTERN = re.compile(r'\b(?:text|typing|type|keyboard)\s+mode\b|\bswitch\s+to\s+(?:text|typing|keyboard)\b')
VOICE_MODE_PATTERN = re.compile(r'\b(?:voice|speech|mic|microphone)\s+mode\b|\bswitch\s+to\s+(?:voice|speech)\b|\bstart listening\b')
WHICH_MODE_PATTERN = re.compile(r'\b(?:what|which)\s+mode\b|\bcurrent mode\b')

# Sticky vs one-shot typing. Default is one-shot: a typed command is a single
# turn and Jupiter drops straight back to the mic afterwards. These let you pin
# it open for a long typing session. Checked BEFORE TEXT_MODE_PATTERN, since
# "stay in text mode" also matches that.
STICKY_TEXT_PATTERN = re.compile(
    r'\b(?:stay|remain|keep me|keep it)\b.*\b(?:text|typing|keyboard)\b'
    r'|\b(?:text|typing|keyboard)\s+mode\s+(?:always|permanently|until i say)\b'
    r'|\bstop auto\s*(?:-|\s)?\s*voice\b'
)
AUTO_VOICE_PATTERN = re.compile(
    r'\b(?:auto|automatic)\s*(?:-|\s)?\s*voice\b'
    r'|\bback to (?:the )?mic\b'
    r'|\b(?:don.t|do not|stop)\b.*\bstay(?:ing)? in text\b'
)

# --- New: vocabulary management --------------------------------------------
VOCAB_SHOW_PATTERN = re.compile(r'\b(?:show|list|what.s in(?: my| your)?)\s+(?:my\s+|your\s+)?vocabulary\b|\bvocabulary list\b')
VOCAB_FORGET_PATTERN = re.compile(r'\b(?:forget|remove|delete)\s+(?:the\s+)?word\s+(.+)')
VOCAB_ON_PATTERN = re.compile(r'\b(?:enable|turn on|start)\s+(?:vocabulary|word)\s+learning\b')
VOCAB_OFF_PATTERN = re.compile(r'\b(?:disable|turn off|stop)\s+(?:vocabulary|word)\s+learning\b')

YES_PATTERN = re.compile(r'^\s*(?:yes|yeah|yep|yup|sure|ok|okay|affirmative|do it|add it|please do|haan|ha)\b')
NO_PATTERN = re.compile(r'^\s*(?:no|nope|nah|don.t|do not|skip|never|negative|nahi)\b')

# Tokens worth considering as "new words". Keeps apostrophes/hyphens inside a
# word (don't, well-known) so they aren't split into fragments.
WORD_TOKEN_PATTERN = re.compile(r"[A-Za-z][A-Za-z'\-]*")

# Every literal word that appears in a command pattern above. A word from this
# set is never treated as "new" — otherwise Jupiter would offer to learn
# "unmute" the first time you ever mute something.
COMMAND_WORDS = {
    "time", "date", "day", "hello", "hi", "hey", "good", "morning", "evening",
    "afternoon", "who", "are", "you", "calculate", "search", "look", "up",
    "google", "find", "translate", "to", "new", "conversation", "convo",
    "previous", "last", "earlier", "summary", "summarise", "summarize",
    "switch", "list", "conversations", "continue", "remind", "me", "reminders",
    "show", "clear", "delete", "open", "file", "quit", "exit", "goodbye",
    "shutdown", "stop", "call", "youtube", "explorer", "files", "play",
    "where", "is", "locate", "location", "of", "navigate", "directions",
    "the", "way", "weather", "temperature", "in", "at", "for", "battery",
    "set", "volume", "mute", "unmute", "increase", "decrease", "turn", "down",
    "english", "hindi", "marathi", "mode", "text", "typing", "type",
    "keyboard", "voice", "speech", "mic", "microphone", "listening",
    "vocabulary", "word", "learning", "enable", "disable", "start", "current",
    "what", "which",
}

# A small everyday-English baseline so Jupiter doesn't interrogate you about
# ordinary words during your first few sessions. Anything NOT here and not a
# command word is a candidate — which is mostly proper nouns, song titles,
# place names and app names, i.e. exactly the words Whisper gets wrong.
BASE_LEXICON = set("""
about above across after again against all almost alone along already also always among and another answer any
anyone anything are around ask away back bad because become been before begin behind being below best better
between big both bring but buy call came can cannot car care carry case change check child city close come
company could country course cut day days dear did different does doing done door down draw drink during each
early eat else end enough even ever every everyone everything example eye face fact fall family far fast feel
few find fine first five follow food foot for force form found four friend from front full game gave get girl
give glad going gone good got great green group grow had half hand happen happy hard has have head hear heard
heart help her here high him his hold home hope hour house how however hundred idea important into its just
keep kept kind knew know known land large last late later laugh lead learn leave left less let letter life
light like line little live long look lost lot love low made make man many may mean meet men might mile mind
minute miss money month more morning most mother move much music must name near need never next night nine
nobody none noon not note nothing now number off often old once one only open or order other our out over own
page paper part pass past people perhaps person pick picture place plan play please point poor possible power
present press pretty problem public pull put question quick quiet quite rain ran reach read ready real really
reason record red remember rest return right river road room round run said same saw say school sea second see
seem seen self sell send sense sent serve set seven several shall she short should show side simple since
sing sir sit six size sleep slow small snow so some someone something sometimes song soon sorry sound speak
special stand star start state stay step still stop story street strong study such summer sun sure table take
talk tall teach tell ten than thank that the their them then there these they thing think third this those
though thought three through throw time today together told tomorrow tonight too took top toward town train
tree true try turn twelve twenty two under until upon use used usual very view visit voice wait walk want war
warm was watch water way weather week well went were west what when where whether which while white who whole
whose why wide will win wind winter wish with within without woman women word work world would write wrong
year yes yesterday yet you young your
""".split())


# --- New: timers, stopwatch, clipboard, system, conversion, news, sky,
#          notes, local documents, usage history ------------------------------
# All read-only, or confined to Jupiter's own data folder. Nothing here deletes
# files outside that folder, kills processes, or changes system settings.
TIMER_SET_PATTERN = re.compile(
    r'\b(?:set|start|update|change)\s+(?:a\s+|an\s+|the\s+)?timer\b\s*(?:for|to|of)?\s+(.+)'
)
TIMER_LIST_PATTERN = re.compile(r'\b(?:show|list|check)\s+(?:my\s+)?timers?\b|\btimers?\s+left\b')
TIMER_CANCEL_PATTERN = re.compile(r'\bcancel\s+(?:my\s+|all\s+|the\s+)?timers?\b')

STOPWATCH_START_PATTERN = re.compile(r'\bstart\s+(?:the\s+)?stopwatch\b')
STOPWATCH_READ_PATTERN = re.compile(r'\b(?:stop|check|read)\s+(?:the\s+)?stopwatch\b|\bhow long on the stopwatch\b')

CLIPBOARD_SUMMARISE_PATTERN = re.compile(r'\bsummar(?:is|iz)e\s+(?:my\s+|the\s+)?clipboard\b')
CLIPBOARD_READ_PATTERN = re.compile(r"\b(?:read|show|what's in)\s+(?:my\s+|the\s+)?clipboard\b")
CLIPBOARD_COPY_PATTERN = re.compile(r'\bcopy\s+(?:that|this|your\s+(?:last\s+)?(?:answer|reply|response))\b')

SYSTEM_STATS_PATTERN = re.compile(
    r'\b(?:system\s+(?:stats|status|info)|cpu\s+usage|memory\s+usage|ram\s+usage|disk\s+space|uptime)\b'
)
WIFI_PATTERN = re.compile(r'\b(?:wifi|wi-fi)\b|\bnetwork name\b')

CONVERT_PATTERN = re.compile(
    r'\b(?:convert|change|how much is|how many)\s+([-\d][\d,.]*)\s*([a-zA-Z\u00b0/]+)\s+(?:to|into|in)\s+([a-zA-Z\u00b0/]+)'
)
NEWS_PATTERN = re.compile(r'\b(?:news|headlines)\b(?:\s+(?:about|on|for|in)\s+(.+))?')
SUN_PATTERN = re.compile(r'\b(sunrise|sunset)\b(?:\s+(?:in|at|for)\s+(.+))?')
MOON_PATTERN = re.compile(r'\bmoon\s*phase\b|\bphase of the moon\b')

NOTE_ADD_PATTERN = re.compile(r'\b(?:note down|take a note|make a note|note that|jot down|add a note)\b[:,]?\s*(.+)', re.IGNORECASE)
NOTE_READ_PATTERN = re.compile(r'\b(?:read|show|list)\s+(?:me\s+)?(?:my\s+)?notes\b')
NOTE_CLEAR_PATTERN = re.compile(r'\b(?:clear|erase|delete)\s+(?:my\s+|all\s+)?notes\b')

DOC_INDEX_PATTERN = re.compile(r'\b(?:index|scan|re-?index)\s+(?:my\s+)?(?:documents|docs|folder)\b(?:\s+(?:at|in)\s+(.+))?')
DOC_ASK_PATTERN = re.compile(
    r'\bsearch\s+my\s+(?:documents|docs|notes)\s+for\s+(.+)'
    r'|\b(?:in|from|according to)\s+my\s+(?:documents|docs|notes)\b[,:]?\s*(.+)',
    re.IGNORECASE
)
DOC_STATUS_PATTERN = re.compile(r'\b(?:document|docs?)\s+(?:index\s+)?status\b|\bwhat have you indexed\b')

HISTORY_STATS_PATTERN = re.compile(r'\b(?:command history|usage stats|most asked|what do i ask you most)\b')

# Offline unit conversion. Each family stores a multiplier to one base unit, so
# any pair inside a family converts with a single multiply. No network, no key.
UNIT_FAMILIES = {
    "length": {
        "mm": 0.001, "millimeter": 0.001, "millimetre": 0.001, "millimeters": 0.001, "millimetres": 0.001,
        "cm": 0.01, "centimeter": 0.01, "centimetre": 0.01, "centimeters": 0.01, "centimetres": 0.01,
        "m": 1.0, "meter": 1.0, "metre": 1.0, "meters": 1.0, "metres": 1.0,
        "km": 1000.0, "kilometer": 1000.0, "kilometre": 1000.0, "kilometers": 1000.0, "kilometres": 1000.0,
        "inch": 0.0254, "inches": 0.0254,
        "foot": 0.3048, "feet": 0.3048, "ft": 0.3048,
        "yard": 0.9144, "yards": 0.9144, "yd": 0.9144,
        "mile": 1609.344, "miles": 1609.344, "mi": 1609.344,
    },
    "mass": {
        "mg": 1e-6, "milligram": 1e-6, "milligrams": 1e-6,
        "g": 0.001, "gram": 0.001, "grams": 0.001,
        "kg": 1.0, "kilogram": 1.0, "kilograms": 1.0, "kilo": 1.0, "kilos": 1.0,
        "tonne": 1000.0, "tonnes": 1000.0, "ton": 1000.0, "tons": 1000.0,
        "oz": 0.028349523125, "ounce": 0.028349523125, "ounces": 0.028349523125,
        "lb": 0.45359237, "lbs": 0.45359237, "pound": 0.45359237, "pounds": 0.45359237,
    },
    "volume": {
        "ml": 0.001, "milliliter": 0.001, "millilitre": 0.001, "milliliters": 0.001, "millilitres": 0.001,
        "l": 1.0, "liter": 1.0, "litre": 1.0, "liters": 1.0, "litres": 1.0,
        "cup": 0.2365882365, "cups": 0.2365882365,
        "pint": 0.473176473, "pints": 0.473176473,
        "quart": 0.946352946, "quarts": 0.946352946,
        "gallon": 3.785411784, "gallons": 3.785411784,
    },
    "speed": {
        "m/s": 1.0, "mps": 1.0,
        "km/h": 0.2777777778, "kmh": 0.2777777778, "kph": 0.2777777778,
        "mph": 0.44704, "mi/h": 0.44704,
        "knot": 0.5144444444, "knots": 0.5144444444,
    },
    "data": {
        "byte": 1.0, "bytes": 1.0,
        "kb": 1024.0, "kilobyte": 1024.0, "kilobytes": 1024.0,
        "mb": 1048576.0, "megabyte": 1048576.0, "megabytes": 1048576.0,
        "gb": 1073741824.0, "gigabyte": 1073741824.0, "gigabytes": 1073741824.0,
        "tb": 1099511627776.0, "terabyte": 1099511627776.0, "terabytes": 1099511627776.0,
    },
}
TEMPERATURE_UNITS = {
    "c": "c", "celsius": "c", "centigrade": "c", "\u00b0c": "c",
    "f": "f", "fahrenheit": "f", "\u00b0f": "f",
    "k": "k", "kelvin": "k",
}
CURRENCY_ALIASES = {
    "rupees": "INR", "rupee": "INR", "dollars": "USD", "dollar": "USD",
    "euros": "EUR", "euro": "EUR", "pounds": "GBP", "pound": "GBP", "yen": "JPY",
}
CURRENCY_CODES = {
    "usd", "eur", "gbp", "inr", "jpy", "aud", "cad", "chf", "cny", "sgd",
    "aed", "nzd", "zar", "sek", "nok", "dkk", "hkd", "krw", "thb", "myr", "brl",
}

# Free, key-less RSS. Google News builds a feed for any topic string.
NEWS_FEEDS = {
    "top": "https://news.google.com/rss?hl=en-IN&gl=IN&ceid=IN:en",
    "india": "https://news.google.com/rss/headlines/section/geo/India?hl=en-IN&gl=IN&ceid=IN:en",
    "world": "https://news.google.com/rss/headlines/section/topic/WORLD?hl=en-IN&gl=IN&ceid=IN:en",
    "technology": "https://news.google.com/rss/headlines/section/topic/TECHNOLOGY?hl=en-IN&gl=IN&ceid=IN:en",
    "tech": "https://news.google.com/rss/headlines/section/topic/TECHNOLOGY?hl=en-IN&gl=IN&ceid=IN:en",
    "business": "https://news.google.com/rss/headlines/section/topic/BUSINESS?hl=en-IN&gl=IN&ceid=IN:en",
    "sports": "https://news.google.com/rss/headlines/section/topic/SPORTS?hl=en-IN&gl=IN&ceid=IN:en",
    "science": "https://news.google.com/rss/headlines/section/topic/SCIENCE?hl=en-IN&gl=IN&ceid=IN:en",
    "health": "https://news.google.com/rss/headlines/section/topic/HEALTH?hl=en-IN&gl=IN&ceid=IN:en",
}
NEWS_SEARCH_URL = "https://news.google.com/rss/search?q={q}&hl=en-IN&gl=IN&ceid=IN:en"

# Local-document Q&A limits. Deliberately conservative: Jupiter only ever READS
# these files, only plain-text formats, and stops well before it could chew
# through an entire drive.
DOC_EXTENSIONS = (".txt", ".md", ".markdown", ".rst", ".csv", ".log")
DOC_MAX_FILES = 300
DOC_MAX_FILE_BYTES = 2_000_000
DOC_CHUNK_CHARS = 1200
DOC_CHUNK_OVERLAP = 150
DOC_EMBED_MODEL = "nomic-embed-text"

# Duration parsing for timers and "remind me in ..." — no dependency needed.
DURATION_PATTERN = re.compile(
    r'(\d+(?:\.\d+)?)\s*(seconds?|secs?|s|minutes?|mins?|m|hours?|hrs?|h|days?|d)\b'
)
DURATION_UNITS = {
    "s": 1, "sec": 1, "secs": 1, "second": 1, "seconds": 1,
    "m": 60, "min": 60, "mins": 60, "minute": 60, "minutes": 60,
    "h": 3600, "hr": 3600, "hrs": 3600, "hour": 3600, "hours": 3600,
    "d": 86400, "day": 86400, "days": 86400,
}
CLOCK_TIME_PATTERN = re.compile(r'\b(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)\b|\b(\d{1,2}):(\d{2})\b')

# Spoken-number -> digit, so "one minute" / "half an hour" parse the same as
# "1 minute" / "30 minutes". STT output is almost always words, not digits,
# so without this DURATION_PATTERN (which requires \d+) never matched things
# like "remind me to call my mother after one minute" at all.
NUMBER_WORDS = {
    "a": 1, "an": 1, "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4,
    "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
}
NUMBER_WORD_PATTERN = re.compile(
    r'\b(' + '|'.join(sorted(NUMBER_WORDS, key=len, reverse=True)) + r')\b', re.I
)


# Common Windows app name -> launch command. Extend this freely; anything not
# listed here falls through to a best-effort `start "<name>"` attempt.
APP_COMMANDS = {
    "notepad": "notepad.exe",
    "calculator": "calc.exe",
    "calc": "calc.exe",
    "paint": "mspaint.exe",
    "cmd": "cmd.exe",
    "command prompt": "cmd.exe",
    "powershell": "powershell.exe",
    "task manager": "taskmgr.exe",
    "control panel": "control.exe",
    "settings": "start ms-settings:",
    "chrome": "chrome.exe",
    "google chrome": "chrome.exe",
    "edge": "msedge.exe",
    "firefox": "firefox.exe",
    "word": "winword.exe",
    "excel": "excel.exe",
    "powerpoint": "powerpnt.exe",
    "spotify": "spotify.exe",
    "vs code": "code.exe",
    "vscode": "code.exe",
    "visual studio code": "code.exe",
}

# Names never launched through the generic shutil.which() fallback in
# open_app(), even though they may legitimately resolve on PATH. Every one of
# these is a system-administration tool where "the user meant to open X" is a
# much less likely explanation than a misheard command.
DANGEROUS_APP_NAMES = {
    "format", "diskpart", "shutdown", "reg", "regedit", "cipher", "bcdedit",
    "fsutil", "del", "erase", "rd", "rmdir", "sfc", "takeown", "icacls",
    "net", "netsh", "wmic", "powershell_ise", "mstsc", "cmdkey", "runas",
}


# --------------------------------------------------------------
#  WAKE PHRASES, LISTENING MODES, GREETINGS & SIGN-OFFS
#  Whisper spells the name many ways ("Jupiter", "Jupyter", "Jupitar"...),
#  so the name pattern is deliberately forgiving.
# --------------------------------------------------------------
LISTEN_ACTIVE = "active"          # always listening (default)
LISTEN_PTT = "push_to_talk"       # mic only opens when you press Enter / Space
LISTEN_SLEEP = "sleep"            # standby: ignores everything except a wake phrase

_WAKE_NAME = r"j(?:u|oo)p[iy]?t[eaiou]r"
_WAKE_LEAD = (
    r"(?:hey|hi|hello|hola|yo|ok|okay|oi|sup|wassup|what.?s up|wake up|wakeup|"
    r"good (?:morning|evening|afternoon)|are you there|you there|rise and shine)"
)
_WAKE_TAIL = (
    r"(?:you there|are you there|wake up|wakeup|where are you|come back|i need you|"
    r"are you (?:awake|up|listening)|you (?:awake|up)|time to wake up|rise and shine|"
    r"hello|hi|there|please|buddy|mate|man|sir)"
)
# "hey jupiter", "sup jupiter", "jupiter, you there?", "wake up jupiter", "jupiter"
WAKE_ONLY_PATTERN = re.compile(
    rf"^\W*(?:{_WAKE_LEAD}[\s,]+)*{_WAKE_NAME}(?![\w'\u2019])(?:[\s,]+{_WAKE_TAIL})*\W*$", re.IGNORECASE
)
# Nameless wake phrases -- only honoured while on standby, never while active.
WAKE_NONAME_PATTERN = re.compile(
    r"^\W*(?:wake up|wakeup|rise and shine|are you there|you there|are you awake|come back|time to wake up)\W*$",
    re.IGNORECASE,
)
WAKE_PREFIX_PATTERN = re.compile(
    rf"^\W*(?P<lead>(?:{_WAKE_LEAD}[\s,]+)+)?{_WAKE_NAME}(?![\w'\u2019])(?P<punct>\s*[,:;.!?\-]+)?\s*", re.IGNORECASE
)
WAKE_TRAILING_PATTERN = re.compile(rf",\s*{_WAKE_NAME}\W*$", re.IGNORECASE)
# A bare "Jupiter <word>" (no hey, no comma) is only treated as addressing the
# assistant when <word> is a command verb -- so "Jupiter has how many moons"
# is still passed to the LLM untouched.
WAKE_COMMAND_VERBS = {
    "what", "whats", "what's", "how", "play", "open", "set", "search", "remind", "tell", "show",
    "start", "stop", "turn", "switch", "translate", "convert", "calculate", "take", "note", "can",
    "could", "would", "please", "find", "where", "who", "when", "why", "give", "read", "list",
    "check", "clear", "cancel", "mute", "unmute", "increase", "decrease", "summarise", "summarize",
    "call", "add", "go", "put", "remember", "launch", "run", "news", "weather", "time", "date",
}

SLEEP_MODE_PATTERN = re.compile(
    r"^(?:please\s+)?(?:"
    r"(?:(?:go|switch|change|enter|activate)\s+(?:to\s+|into\s+)?)?(?:sleep|standby|stand\s+by|nap)(?:\s+mode)?(?:\s+now)?"
    r"|rest(?:\s+now)?|you\s+can\s+(?:rest|sleep)(?:\s+now)?"
    r"|take\s+a\s+(?:nap|break)|power\s+nap|time\s+to\s+sleep|that.?s\s+all(?:\s+for\s+now)?|dismissed"
    rf")(?:\s+{_WAKE_NAME})?\W*$",
    re.IGNORECASE,
)
PTT_MODE_PATTERN = re.compile(
    r"^(?:please\s+)?(?:(?:switch|change|go|turn|enter|enable|activate|start)\s+(?:on\s+|to\s+|into\s+)?)?"
    r"(?:push[\s-]*to[\s-]*talk|press[\s-]*to[\s-]*talk|hold[\s-]*to[\s-]*talk|walkie[\s-]*talkie|p\.?t\.?t\.?)"
    rf"(?:\s+mode)?(?:\s+{_WAKE_NAME})?\W*$",
    re.IGNORECASE,
)
ACTIVE_MODE_PATTERN = re.compile(
    r"^(?:please\s+)?(?:(?:switch|change|go|turn|come|get|enter|enable|activate|resume)\s+(?:back\s+)?(?:on\s+)?(?:to\s+)?)?"
    r"(?:always[\s-]*(?:on|listening)|continuous(?:ly)?(?:\s+listening)?|hands[\s-]*free|normal|active|open[\s-]*mic)"
    rf"(?:\s+(?:listening|mode))*(?:\s+{_WAKE_NAME})?\W*$",
    re.IGNORECASE,
)

# --- Long-term memory ("remember that ...") and conversation recall ---------
REMEMBER_FACT_PATTERN = re.compile(
    r"^\s*(?:please\s+)?(?:remember|keep in mind|don.?t forget)\s+that\s+(.+)", re.IGNORECASE
)
RECALL_FACTS_PATTERN = re.compile(
    r"\bwhat do you (?:remember|know) about me\b|^\s*what do you remember\W*$"
    r"|\b(?:show|list)\s+(?:me\s+)?(?:my\s+|your\s+)?(?:memories|facts)\b|\bwhat have i told you\b",
    re.IGNORECASE,
)
FORGET_FACTS_PATTERN = re.compile(
    r"\b(?:forget|erase|clear)\s+(?:everything|all)\b.*\b(?:about me|memories|memory|facts)\b"
    r"|\b(?:clear|erase|wipe)\s+(?:your\s+|my\s+)?(?:memory|memories)\b",
    re.IGNORECASE,
)
WHAT_DISCUSSED_PATTERN = re.compile(
    r"\bwhat (?:did|have) we (?:talk(?:ed)?|discuss(?:ed)?|speak|spoke)\b"
    r"|\brecap (?:our|the|this) (?:conversation|chat|talk)\b|\bwhat were we (?:talking|discussing)\b",
    re.IGNORECASE,
)
RECALL_EARLIER_WORDS = re.compile(r"\b(?:last time|previous|before|yesterday|earlier|last conversation)\b")

# Phrase pools. {u} = how Jupiter addresses you. _pick() never repeats the
# line it used last time from the same pool.
STARTUP_GREETINGS = [
    "Good {tod}, {u}. I am JUPITER, at your service.",
    "Good {tod}, {u}. JUPITER online and ready.",
    "Welcome back, {u}. Good {tod}. JUPITER is up and running.",
    "Good {tod}, {u}! JUPITER here, ready when you are.",
    "Good {tod}, {u}. All systems are up. How can I help today?",
]
GREETING_REPLIES = [
    "Hello, {u}. How can I help?",
    "Hey {u}! What can I do for you?",
    "Hi there, {u}. I'm all ears.",
    "Good to hear from you, {u}. What do you need?",
    "At your service, {u}.",
    "Hello {u}! Ready when you are.",
    "Hey, {u}. What's on your mind?",
]
TIMED_GREETING_REPLIES = [
    "{greet}, {u}. How can I help?",
    "{greet}, {u}! What can I do for you?",
    "{greet} to you too, {u}. What do you need?",
]
WAKE_ACKS = [
    "Yes, {u}?", "I'm here, {u}.", "Right here, {u}. What do you need?",
    "At your service, {u}.", "Listening, {u}.", "You called, {u}?",
    "Present and ready, {u}.", "Yes? I'm all ears, {u}.",
]
SLEEP_ENTER = [
    "Going on standby, {u}. Say hey Jupiter when you need me.",
    "Standing by, {u}. Just call my name.",
    "Resting now, {u}. I'll wake the moment you call.",
    "Quiet mode on, {u}. Say my name and I'm back.",
    "Alright {u}, I'll stay on standby.",
]
WAKE_FROM_SLEEP = [
    "I'm back, {u}. What do you need?", "Awake and ready, {u}.",
    "Welcome back, {u}. I'm listening.", "Up and running, {u}. How can I help?",
    "Good to hear you, {u}. I'm all ears.",
]
PTT_ENTER = [
    "Push to talk is on, {u}. Press Enter or Space, then speak.",
    "Switching to push to talk, {u}. Tap Enter or Space when you want me.",
    "Understood, {u}. I'll only listen when you press Enter or Space.",
]
ACTIVE_ENTER = [
    "Back to always listening, {u}.", "Hands-free mode on, {u}. I'm listening.",
    "Always-on listening, {u}. Go ahead.",
]
SIGN_OFFS = [
    "Goodbye, {u}. JUPITER signing off.", "See you later, {u}.",
    "Shutting down. Take care, {u}.", "Until next time, {u}.",
    "Signing off, {u}. Have a great one.", "Catch you later, {u}.",
]
SIGN_OFFS_NIGHT = [
    "Good night, {u}. Sleep well.", "Good night, {u}. JUPITER signing off.",
    "Rest well, {u}. See you tomorrow.",
]
MEMORY_SAVED = [
    "Noted, {u}. I'll remember that.", "Got it, {u}. That's stored.",
    "I'll keep that in mind, {u}.",
]




__all__ = [name for name in globals() if not name.startswith("__")]
