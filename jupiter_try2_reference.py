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
if sys.platform == "win32":
    # Two places we look for cuBLAS / cuDNN, in this order:
    #   1. C:\JUPITER\cuda_libs  (drop cublas64_12.dll, cublasLt64_12.dll and the
    #      cudnn*64_9.dll files here if you prefer not to use pip packages)
    #   2. the NVIDIA pip packages:  pip install nvidia-cublas-cu12 "nvidia-cudnn-cu12==9.*"
    # Each folder is registered with add_dll_directory AND put on PATH, because
    # native libraries sometimes ignore add_dll_directory on its own.
    _dll_dirs = [os.path.join(os.path.dirname(os.path.abspath(__file__)), "cuda_libs")]
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
 
try:
    import argostranslate.translate
    translate_available = True
except ImportError:
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
DATE_PATTERN = re.compile(r"^(?:date|what(?:.s| is)\s+(?:the\s+)?date|what\s+day\s+is\s+it|what\s+is\s+today.s\s+date|tell\s+me(?:\s+today.s|\s+the)?\s+date|today.s\s+date|today\s+date)(?:[.!?])?$", re.IGNORECASE)
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
    r'^(?:(?:ok|okay|alright|all right|right)[,\s]+)?'
    r'(?:quit|exit|goodbye|good\s*bye|bye[\s-]*bye|good\s*night|see\s+you(?:\s+(?:later|tomorrow|soon))?'
    r'|shut\s*down|power\s+off|sign\s+off|take\s+care|catch\s+you\s+later)'
    r'(?:\s+jupiter)?[.!?\s]*$',
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
YOUTUBE_SEARCH_PATTERN = re.compile(r'(?:search|look up|find)\s+(.+?)\s+on\s+youtube\b')
YOUTUBE_OPEN_PATTERN = re.compile(r'^open\b[,.]?\s+youtube$')
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


class Jupiter:
    def __init__(self):
        self.name = "Jupiter"
        self.user_name = "sir"
        self.ollama_url = "http://localhost:11434/api/chat"
        self.is_running = True
        self.sample_rate = 16000
        self.max_listen_duration = 15   # hard safety cap, seconds
        # "base" mishears proper nouns constantly (e.g. "Harry Potter" -> "High
        # Reporter"). "small" is ~3x the params — meaningfully better on names,
        # titles and places at a modest speed cost. Bump to "medium" if you
        # want even more accuracy and your hardware handles it; drop back to
        # "base" if voice commands start feeling sluggish.
        # Override without editing code:  $env:JUPITER_WHISPER = "base"  (faster)
        # or "medium" (more accurate, wants the GPU).
        self.whisper_model_size = os.environ.get("JUPITER_WHISPER", "small")
        self.silence_limit = 0.7        # quiet after a SHORT command that ends the recording (seconds)
        self.silence_limit_long = 1.1   # quiet that ends a longer sentence (people pause mid-sentence more)
        self.vad_threshold = 0.5        # Silero speech probability needed (0.4 = more sensitive, 0.6 = stricter)
        self.audio_cleanup = True       # high-pass filter + gentle gain before Whisper
        # Spoken interrupt ("stop"): while Jupiter talks, a small listener watches
        # the mic. Headphones make it rock solid. On laptop speakers it only reacts
        # to you being clearly LOUDER than Jupiter's own voice leaking into the mic:
        # lower barge_in_ratio (1.3) if it misses you, raise it (2.2) if it
        # pauses for no reason, or set barge_in_enabled = False to turn it off.
        self.barge_in_enabled = True
        self.barge_in_ratio = 1.6
        self.barge_in_min_rms = 0.025
        # True  = speech is synthesised in memory and played through sounddevice
        #         in tiny blocks (gapless, interruptible).
        # False = the old route: write a temp .wav, play it with winsound, delete
        #         it (works, but cannot be interrupted mid-sentence).
        self.tts_in_memory = True
        self.min_speech_duration = 0.3  # seconds of sound needed to count as real speech
        self.silence_threshold = 0.02   # RMS level below this = silence (tune per mic/room)
        # STT language: forced (not auto-detected). Whisper's auto language
        # detection is unreliable on short, code-switched clips ("play mann
        # mera" mixes an English verb with a Hindi song name) and can lock
        # the WHOLE utterance onto a random wrong language. Forcing "en" by
        # default keeps command words reliable and transliterates Hindi/
        # Marathi proper nouns phonetically into Latin script instead of
        # garbling them. Say "hindi mode" / "marathi mode" / "english mode"
        # to switch when you want a real conversation in that language.
        self.stt_language = "en"
        self.STT_LANGUAGES = {"english": "en", "hindi": "hi", "marathi": "mr"}
        # Song/artist titles you say often — add to this list anytime to help
        # Whisper transliterate them correctly instead of guessing phonetically.
        self.favorite_songs = [
            "Mann Mera", "High On You", "Vaaroon Forever",
        ]
        # Input mode: "voice" or "text". Persisted, so Jupiter comes back up in
        # whichever mode you left it in. See listen_for_command() for the
        # per-turn escape hatches that let you cross modes without a command.
        self.input_mode = "voice"
        # When True (the default), a typed command is a ONE-SHOT: the next turn
        # goes straight back to the microphone. Say "stay in text mode" to pin
        # the keyboard open for a longer session.
        self.auto_return_to_voice = True
        # Whether to offer to learn unfamiliar words after a successful command.
        self.vocab_learning = True
        # Listening mode (separate from voice/text input): "active" = always
        # listening, "push_to_talk" = press Enter/Space to speak, "sleep" =
        # standby until a wake phrase. Sleep is never persisted.
        self.listen_mode = LISTEN_ACTIVE
        self._mode_before_sleep = LISTEN_ACTIVE
        self._last_pick = {}
        self._vocab_version = 0
        self._vocab_hint_cache = None
        self._geo_cache = {}
        # One keep-alive HTTP session for Ollama / Nominatim: avoids a new TCP
        # handshake on every request.
        self.http = requests.Session()
        self._init_speech_engine()
        self._other_place_re = re.compile(
            r"\b(?:" + "|".join(sorted((re.escape(c) for c in self._KNOWN_OTHER_CITIES), key=len, reverse=True)) + r")\b"
        )
        self.setup_memory()
        self._load_user_name()
        self._load_settings()
        self._load_vocabulary()
        self.setup_audio_models()
        # Continue with the last conversation instead of creating a new one.
        # Resolved BEFORE start_scheduler() so this one-time read+write of
        # self.conn can't race the scheduler thread's first poll.
        self.current_conv_id = self._get_or_create_conversation()
        self.start_scheduler()
        if not self._voice_possible():
            self.input_mode = "text"
        mode_note = "Voice mode" if self.input_mode == "voice" else "Text mode"
        if self.listen_mode == LISTEN_PTT and self._voice_possible():
            mode_note += ", push to talk"
        self.speak(
            self._pick(STARTUP_GREETINGS, tod=self._greeting_period()) + " "
            f"Continuing conversation #{self.current_conv_id}. {mode_note}."
        )
        self._warm_up_ollama()
 
    def _load_user_name(self):
        """Load a previously saved address term (e.g. 'sir', 'boss', a name), if any."""
        cursor = self.conn.execute(
            "SELECT value FROM metadata WHERE key = 'user_name'"
        )
        row = cursor.fetchone()
        if row and row[0]:
            self.user_name = row[0]
 
    def set_user_name(self, name: str):
        """Update and persist how JUPITER addresses the user."""
        name = name.strip()
        if not name:
            return
        self.user_name = name
        with self._db_lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
                ("user_name", name)
            )
            self.conn.commit()
 
    # --------------------------------------------------------------
    #  SETTINGS  (input mode, vocabulary learning) — persisted in metadata
    # --------------------------------------------------------------
    def _load_settings(self):
        """Restore input mode and vocabulary-learning preference from last run."""
        rows = dict(self.conn.execute(
            "SELECT key, value FROM metadata WHERE key IN "
            "('input_mode', 'vocab_learning', 'auto_return_to_voice', 'listen_mode')"
        ).fetchall())
        if rows.get("input_mode") in ("voice", "text"):
            self.input_mode = rows["input_mode"]
        if rows.get("vocab_learning") in ("0", "1"):
            self.vocab_learning = rows["vocab_learning"] == "1"
        if rows.get("auto_return_to_voice") in ("0", "1"):
            self.auto_return_to_voice = rows["auto_return_to_voice"] == "1"
        if rows.get("listen_mode") == LISTEN_PTT:
            self.listen_mode = LISTEN_PTT
 
    def _save_setting(self, key: str, value: str):
        with self._db_lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)", (key, value)
            )
            self.conn.commit()
 
    def set_input_mode(self, mode: str, announce: bool = True):
        """Switch between voice and text input, and remember the choice."""
        mode = mode.lower().strip()
        if mode not in ("voice", "text"):
            return
        if mode == "voice" and not self._voice_possible():
            self.speak("Voice input isn't available on this machine, sir. Staying in text mode.")
            self.input_mode = "text"
            self._save_setting("input_mode", "text")
            return
        self.input_mode = mode
        self._save_setting("input_mode", mode)
        if announce:
            if mode == "text":
                if self.auto_return_to_voice:
                    self.speak("Go ahead and type, sir. I'll be listening again right after.")
                else:
                    self.speak("Text mode, sir. Type your commands. Press Enter on an empty line to speak one instead.")
            else:
                self.speak("Voice mode, sir. I'm listening. Start typing at any time to switch to the keyboard.")
 
    def _voice_possible(self) -> bool:
        """True only if we can actually record AND transcribe."""
        return (
            audio_input_available
            and whisper_available
            and hasattr(self, "whisper_model")
        )
 
    # --------------------------------------------------------------
    #  VOCABULARY LEARNING
    #  Whisper's initial_prompt biases decoding toward words you supply. Every
    #  time a command SUCCEEDS but contains a word Jupiter has never seen, it
    #  asks permission to remember it — so the spelling that worked once keeps
    #  working, instead of being re-guessed phonetically every session.
    # --------------------------------------------------------------
    def _load_vocabulary(self):
        """Load accepted/rejected words and build the 'already known' word set."""
        self.vocab_accepted = {}   # lowercase word -> display form
        self.vocab_rejected = set()
        try:
            for word, display, status in self.conn.execute(
                "SELECT word, display, status FROM vocabulary"
            ):
                if status == "accepted":
                    self.vocab_accepted[word] = display or word
                else:
                    self.vocab_rejected.add(word)
        except sqlite3.Error as e:
            print(f"[Vocabulary Load Error] {e}")
 
        self.known_words = set(BASE_LEXICON) | set(COMMAND_WORDS)
        self.known_words |= {k for key in APP_COMMANDS for k in key.split()}
        for song in self.favorite_songs:
            self.known_words |= {w.lower() for w in WORD_TOKEN_PATTERN.findall(song)}
        self.known_words |= set(self.vocab_accepted)
 
    def _build_vocab_hint(self) -> str:
        """Assemble Whisper's initial_prompt: fixed command words + favourite
        songs + the most-used learned words. Kept short on purpose — Whisper
        caps initial_prompt at ~224 tokens and a bloated prompt makes decoding
        worse, not better, so only the top learned words ride along.
 
        LANGUAGE-MATCHED to self.stt_language: initial_prompt is a biasing
        signal, not just a glossary, and mixing Hindi/Marathi phrases into a
        prompt used while decoding is forced to English can nudge Whisper
        toward code-switched or garbled phonetic guesses on short, ambiguous
        clips (e.g. a song title) — plausibly the exact mechanism behind
        outputs like "Lehaayon" for what was actually meant to be a normal
        English phrase. The Hindi/Marathi example words now only ride along
        when Jupiter is actually decoding in that language."""
        cache_key = (self.stt_language, self._vocab_version)
        cached = self._vocab_hint_cache
        if cached is not None and cached[0] == cache_key:
            return cached[1]
        with self._db_lock:
            learned = [
                display for (display,) in self.conn.execute(
                    "SELECT COALESCE(display, word) FROM vocabulary "
                    "WHERE status = 'accepted' ORDER BY hits DESC, added_at DESC LIMIT 40"
                )
            ]
        command_words = (
            "Play, open, search, weather, battery, volume, mute, unmute, "
            "YouTube, file explorer, text mode, voice mode, Jupiter, remind me, timer, "
            "stopwatch, note, news, translate, convert, calculate, conversation."
        )
        parts = [command_words]
        if self.stt_language in ("hi", "mr"):
            parts.append("Nagpur, Sitabuldi, Dharampeth, mausam, gaana, kaisa hai.")
        parts.append(", ".join(self.favorite_songs))
        if learned:
            parts.append(", ".join(learned))
        hint = ", ".join(p for p in parts if p)[:900]
        self._vocab_hint_cache = (cache_key, hint)
        return hint
 
    def _vocab_candidates(self, command: str) -> list:
        """Words in a command that Jupiter has never seen before, in order,
        deduplicated. Filters out short tokens, digits, anything already
        known/accepted/previously declined, AND anything in a real English
        dictionary (via pyspellchecker) — so ordinary words never get flagged
        just because they're missing from the small hand-typed BASE_LEXICON."""
        candidates = []
        seen = set()
        for token in WORD_TOKEN_PATTERN.findall(command):
            key = token.lower().strip("'-")
            if len(key) < 3 or not key.isalpha():
                continue
            if key in self.known_words or key in self.vocab_rejected or key in seen:
                continue
            if spellchecker_available and key in _spell:
                continue
            seen.add(key)
            candidates.append(token.strip("'-"))
        return candidates
 
    def maybe_learn_vocabulary(self, command: str):
        """Called only after a command was handled successfully. Offers to add
        up to two unfamiliar words per turn — more than that turns a single
        command into an interrogation."""
        if not self.vocab_learning or not command:
            return
        for word in self._vocab_candidates(command)[:2]:
            answer = self.ask_yes_no(
                f'"{word}" is new to me, {self.user_name}. '
                f'Shall I add it to my vocabulary?'
            )
            if answer is True:
                self.add_vocabulary_word(word)
            elif answer is False:
                self.reject_vocabulary_word(word)
            else:
                # Unclear answer — don't record anything, just move on. The word
                # stays a candidate, so it'll be offered again next time.
                self.speak("I'll leave it for now, sir.")
 
    def add_vocabulary_word(self, word: str, announce: bool = True):
        key = word.lower().strip("'-")
        if not key:
            return
        now = self._get_ist_time().isoformat()
        with self._db_lock:
            self.conn.execute(
                """
                INSERT INTO vocabulary (word, display, status, hits, added_at)
                VALUES (?, ?, 'accepted', 1, ?)
                ON CONFLICT(word) DO UPDATE SET
                    status = 'accepted', hits = hits + 1, display = excluded.display
                """,
                (key, word, now)
            )
            self.conn.commit()
        self.vocab_accepted[key] = word
        self.vocab_rejected.discard(key)
        self.known_words.add(key)
        self._vocab_version += 1
        if announce:
            self.speak(f"Added {word} to my vocabulary, sir.")
 
    def reject_vocabulary_word(self, word: str):
        key = word.lower().strip("'-")
        now = self._get_ist_time().isoformat()
        with self._db_lock:
            self.conn.execute(
                """
                INSERT INTO vocabulary (word, display, status, hits, added_at)
                VALUES (?, ?, 'rejected', 0, ?)
                ON CONFLICT(word) DO UPDATE SET status = 'rejected'
                """,
                (key, word, now)
            )
            self.conn.commit()
        self.vocab_rejected.add(key)
        self.vocab_accepted.pop(key, None)
        self._vocab_version += 1
        self.speak("Understood, sir. I won't ask about that one again.")
 
    def show_vocabulary(self):
        with self._db_lock:
            rows = self.conn.execute(
                "SELECT COALESCE(display, word), hits FROM vocabulary "
                "WHERE status = 'accepted' ORDER BY hits DESC, added_at DESC"
            ).fetchall()
        if not rows:
            self.speak("I haven't learned any new words yet, sir.")
            return
        words = ", ".join(f"{w}" for w, _ in rows)
        self.speak(f"I've learned {len(rows)} word(s), sir: {words}")
 
    def forget_vocabulary_word(self, word: str):
        key = word.lower().strip(" .!?'-")
        with self._db_lock:
            cursor = self.conn.execute("DELETE FROM vocabulary WHERE word = ?", (key,))
            self.conn.commit()
        if cursor.rowcount:
            self.vocab_accepted.pop(key, None)
            self.vocab_rejected.discard(key)
            self.known_words.discard(key)
            self._vocab_version += 1
            self.speak(f"Forgotten, sir. {word} is out of my vocabulary.")
        else:
            self.speak(f"I don't have {word} in my vocabulary, sir.")
 
    def ask_yes_no(self, question: str):
        """Ask a yes/no question using whichever input mode is active, so the
        prompt is answerable the same way the command was given. Returns True,
        False, or None if the answer wasn't a clear yes or no."""
        self._interrupted.clear()   # a fresh question is always worth speaking
        self.speak(question)
        reply = self.get_input("Answer (yes/no): ")
        if not reply:
            return None
        reply = reply.lower().strip()
        if YES_PATTERN.match(reply):
            return True
        if NO_PATTERN.match(reply):
            return False
        return None
 
    def get_input(self, prompt: str = "You: ") -> str:
        """One turn of input in the current mode. Used for confirmations, where
        we do NOT want the mode-switch escape hatches firing mid-question."""
        if self.input_mode == "text" or not self._voice_possible():
            return self._read_text_input(prompt)
        return self._listen_voice_input(keep_short=True)
 
    def setup_memory(self):
        """Create persistent SQLite database with conversation support"""
        self.data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
        os.makedirs(self.data_dir, exist_ok=True)
        db_path = os.path.join(self.data_dir, "jupiter_memory.db")
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        # The scheduler runs on its own thread and touches this same
        # connection. SQLite already serializes writes internally, but
        # without a generous busy timeout a write from one thread landing
        # mid-transaction on the other raises "database is locked" instead of
        # just waiting the few milliseconds it actually needs.
        self.conn.execute("PRAGMA busy_timeout = 5000")
        # Created here (not in start_scheduler) so every self.conn access
        # anywhere in the class — including ones that happen during __init__,
        # before the scheduler thread even starts — has this lock available
        # from the moment the connection exists.
        self._db_lock = threading.Lock()
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conv_id INTEGER NOT NULL DEFAULT 1,
                timestamp TEXT,
                role TEXT,
                message TEXT,
                summary TEXT
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        # Create conversation_threads table for tracking conversation metadata
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS conversation_threads (
                conv_id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT,
                summary TEXT
            )
        """)
        # Learned vocabulary. status is 'accepted' (feed it to Whisper as a
        # spelling hint) or 'rejected' (never ask about this word again).
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS vocabulary (
                word TEXT PRIMARY KEY,
                display TEXT,
                status TEXT NOT NULL DEFAULT 'accepted',
                hits INTEGER DEFAULT 1,
                added_at TEXT
            )
        """)
        # Embedded chunks of your own plain-text documents, for local Q&A.
        # Stores a copy of the text plus its vector — your originals are only
        # ever opened read-only.
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path TEXT NOT NULL,
                chunk_index INTEGER,
                text TEXT,
                embedding BLOB,
                mtime TEXT,
                indexed_at TEXT
            )
        """)
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_documents_path ON documents(path)")
        # Long-term facts the user asked Jupiter to remember ("remember that ...").
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS memory_facts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fact TEXT NOT NULL,
                created_at TEXT
            )
        """)
        # Reminder lookups run every few seconds from the scheduler thread
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task TEXT,
                due_time TEXT,
                created_time TEXT,
                completed INTEGER DEFAULT 0
            )
        """)
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_reminders_due ON reminders(completed, due_time)"
        )
        # Migrate old conversations (no conv_id) to conv_id = 1
        try:
            columns = [row[1] for row in self.conn.execute("PRAGMA table_info(conversations)")]
            if "conv_id" not in columns:
                self.conn.execute("ALTER TABLE conversations ADD COLUMN conv_id INTEGER NOT NULL DEFAULT 1")
            if "summary" not in columns:
                self.conn.execute("ALTER TABLE conversations ADD COLUMN summary TEXT")
        except sqlite3.Error as e:
            # One-time schema migration; a failure here just means the
            # columns already matched some other way. Narrowed from a bare
            # except so a real interrupt (Ctrl-C during startup) isn't
            # silently swallowed along with it.
            print(f"[Migration Note] {e}")
        self.conn.commit()
 
    # --------------------------------------------------------------
    #  CONVERSATION MANAGEMENT
    # --------------------------------------------------------------
    def _get_or_create_conversation(self) -> int:
        """Load last conversation ID, or create a new one if none exists."""
        with self._db_lock:
            cursor = self.conn.execute(
                "SELECT value FROM metadata WHERE key = 'last_conv_id'"
            )
            row = cursor.fetchone()
            if row:
                conv_id = int(row[0])
                # Verify it exists in conversation_threads
                check = self.conn.execute(
                    "SELECT 1 FROM conversation_threads WHERE conv_id = ? LIMIT 1", (conv_id,)
                ).fetchone()
                if check:
                    return conv_id
            # No existing conversation — create one
            now = self._get_ist_time().isoformat()
            cursor = self.conn.execute(
                "INSERT INTO conversation_threads (created_at, summary) VALUES (?, ?)",
                (now, None)
            )
            new_id = cursor.lastrowid
            self.conn.execute(
                "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
                ("last_conv_id", str(new_id))
            )
            self.conn.commit()
            return new_id
 
    def set_current_conversation(self, conv_id: int):
        """Switch to a different conversation thread."""
        with self._db_lock:
            check = self.conn.execute(
                "SELECT 1 FROM conversation_threads WHERE conv_id = ? LIMIT 1", (conv_id,)
            ).fetchone()
            if check:
                self.current_conv_id = conv_id
                self.conn.execute(
                    "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
                    ("last_conv_id", str(conv_id))
                )
                self.conn.commit()
                # Get summary if exists
                summary_row = self.conn.execute(
                    "SELECT summary FROM conversation_threads WHERE conv_id = ?", (conv_id,)
                ).fetchone()
            else:
                summary_row = None
        if check:
            summary = summary_row[0] if summary_row and summary_row[0] else None
            if summary:
                self.speak(f"Switched to conversation #{conv_id}, sir. Previous summary: {summary[:100]}...")
            else:
                self.speak(f"Switched to conversation #{conv_id}, sir.")
        else:
            self.speak(f"Conversation #{conv_id} does not exist, sir.")
 
    def list_conversations(self):
        """Show all available conversation threads."""
        with self._db_lock:
            cursor = self.conn.execute("""
                SELECT ct.conv_id, ct.created_at, ct.summary,
                       (SELECT COUNT(*) FROM conversations c WHERE c.conv_id = ct.conv_id AND c.role IN ('user', 'jupiter')) as msgs
                FROM conversation_threads ct
                ORDER BY ct.created_at DESC
            """)
            rows = cursor.fetchall()
        if not rows:
            self.speak("No conversations found, sir.")
            return
        self.speak(f"You have {len(rows)} conversation(s), sir:")
        for conv_id, created_at, summary, msgs in rows:
            try:
                dt = datetime.fromisoformat(created_at)
                time_str = dt.strftime("%b %d, %H:%M")
            except Exception:
                time_str = created_at
            summary_msg = " (summarised)" if summary else ""
            self.speak(f"Conversation #{conv_id}: started {time_str}, {msgs} messages{summary_msg}")
 
    def _fetch_recent_context(self, limit: int = 6) -> list:
        """Return last exchanges from the current conversation for LLM context."""
        with self._db_lock:
            cursor = self.conn.execute("""
                SELECT role, message
                FROM conversations
                WHERE conv_id = ? AND role IN ('user', 'jupiter')
                ORDER BY id DESC
                LIMIT ?
            """, (self.current_conv_id, limit))
            rows = cursor.fetchall()
        # Ollama's chat API expects {"role", "content"} and only recognizes
        # "system"/"user"/"assistant" — map our stored "jupiter" role accordingly.
        return [
            {"role": "assistant" if r == "jupiter" else r, "content": m}
            for r, m in reversed(rows)
        ]
 
    def _get_conversation_summary(self) -> str:
        """Get stored summary for current conversation."""
        with self._db_lock:
            cursor = self.conn.execute(
                "SELECT summary FROM conversation_threads WHERE conv_id = ?",
                (self.current_conv_id,)
            )
            row = cursor.fetchone()
        return row[0] if row and row[0] else ""
 
    def _get_previous_conversation_id(self):
        """Return the conv_id of the conversation thread immediately before the
        current one (by creation order), or None if there isn't one."""
        with self._db_lock:
            cursor = self.conn.execute(
                "SELECT conv_id FROM conversation_threads WHERE conv_id < ? ORDER BY conv_id DESC LIMIT 1",
                (self.current_conv_id,)
            )
            row = cursor.fetchone()
        return row[0] if row else None
 
    def _get_or_generate_summary(self, conv_id: int):
        """Return a conversation's stored summary, generating and caching one on
        the fly if it doesn't have one yet. Returns None if it has no messages."""
        with self._db_lock:
            cursor = self.conn.execute(
                "SELECT summary FROM conversation_threads WHERE conv_id = ?", (conv_id,)
            )
            row = cursor.fetchone()
        if row and row[0]:
            return row[0]
 
        conv_text = self._fetch_conversation_text(conv_id)
        if not conv_text:
            return None
 
        summary = self._call_summary_api(conv_text)
        if summary:
            with self._db_lock:
                self.conn.execute(
                    "UPDATE conversation_threads SET summary = ? WHERE conv_id = ?",
                    (summary, conv_id)
                )
                self.conn.commit()
        return summary
 
    def _fetch_conversation_text(self, conv_id: int):
        """Return the full transcript of a conversation as 'role: message' lines,
        or None if it has no messages yet."""
        with self._db_lock:
            cursor = self.conn.execute("""
                SELECT role, message
                FROM conversations
                WHERE conv_id = ? AND role IN ('user', 'jupiter')
                ORDER BY id ASC
            """, (conv_id,))
            rows = cursor.fetchall()
        if not rows:
            return None
        return "\n".join([f"{role}: {msg}" for role, msg in rows])
 
    def _call_summary_api(self, conv_text: str):
        """Ask the LLM to summarise a transcript in 2-3 sentences. Returns None on failure."""
        summary_prompt = f"Summarise this conversation concisely in 2-3 sentences:\n\n{conv_text}"
        try:
            response = self.http.post(
                self.ollama_url,
                json={
                    "model": LLM_MODEL, "think": False,
                    "messages": [
                        {"role": "system", "content": "You are a helpful assistant that summarises conversations. Provide brief, clear summaries."},
                        {"role": "user", "content": summary_prompt}
                    ],
                    "stream": False,
                    "keep_alive": "30m",
                    "options": {"temperature": 0.3, "num_predict": 100}
                },
                timeout=30
            )
            if response.status_code == 200:
                return response.json()["message"]["content"].strip()
            return None
        except Exception:
            return None
 
    def summarise_conversation(self):
        """Generate and store a summary of the current conversation, and speak it."""
        conv_text = self._fetch_conversation_text(self.current_conv_id)
        if conv_text is None:
            self.speak(f"No messages to summarise in this conversation, {self.user_name}.")
            return
 
        summary = self._call_summary_api(conv_text)
        if summary is None:
            self.speak(f"Failed to generate summary, {self.user_name}.")
            return
 
        with self._db_lock:
            self.conn.execute(
                "UPDATE conversation_threads SET summary = ? WHERE conv_id = ?",
                (summary, self.current_conv_id)
            )
            self.conn.commit()
        self.speak(f"Conversation summarised, {self.user_name}: {summary}")
 
    # --------------------------------------------------------------
    #  LONG-TERM MEMORY  ("remember that my sister's birthday is 5 March")
    #  Stored in SQLite, fed into the LLM's system prompt on every turn, so
    #  it survives restarts and works across conversation threads.
    # --------------------------------------------------------------
    def remember_fact(self, fact: str):
        fact = fact.strip().rstrip(".!?").strip()[:300]
        if not fact:
            self.speak(f"What should I remember, {self.user_name}?")
            return
        with self._db_lock:
            exists = self.conn.execute(
                "SELECT 1 FROM memory_facts WHERE lower(fact) = ? LIMIT 1", (fact.lower(),)
            ).fetchone()
            if not exists:
                self.conn.execute(
                    "INSERT INTO memory_facts (fact, created_at) VALUES (?, ?)",
                    (fact, self._get_ist_time().isoformat())
                )
                self.conn.commit()
        if exists:
            self.speak(f"I already have that one, {self.user_name}.")
        else:
            self.speak(self._pick(MEMORY_SAVED))

    def _facts_for_prompt(self) -> str:
        try:
            with self._db_lock:
                rows = self.conn.execute(
                    "SELECT fact FROM memory_facts ORDER BY id DESC LIMIT 20"
                ).fetchall()
        except sqlite3.Error:
            return ""
        return "\n".join(f"- {r[0]}" for r in reversed(rows))

    def recall_facts(self):
        with self._db_lock:
            rows = self.conn.execute("SELECT fact FROM memory_facts ORDER BY id ASC").fetchall()
        if not rows:
            self.speak(f"I'm not holding on to anything yet, {self.user_name}. Say 'remember that' followed by a fact.")
            return
        for i, (fact,) in enumerate(rows, 1):
            print(f"  {i}. {fact}")
        spoken = "; ".join(f for (f,) in rows[-8:])
        more = f" Showing the latest {min(8, len(rows))} of {len(rows)}." if len(rows) > 8 else ""
        self.speak(f"I remember {len(rows)} thing(s), {self.user_name}: {spoken}.{more}")

    def forget_facts(self):
        with self._db_lock:
            count = self.conn.execute("SELECT COUNT(*) FROM memory_facts").fetchone()[0]
        if not count:
            self.speak(f"There's nothing to forget, {self.user_name}.")
            return
        answer = self.ask_yes_no(f"That will erase {count} remembered fact(s), {self.user_name}. Are you sure?")
        if answer is True:
            with self._db_lock:
                self.conn.execute("DELETE FROM memory_facts")
                self.conn.commit()
            self.speak(f"Done, {self.user_name}. My long-term memory is cleared.")
        else:
            self.speak(f"Alright, I'll keep them, {self.user_name}.")

    def recall_discussion(self, cmd: str):
        """'What did we talk about?' -> this conversation's summary, or the
        previous conversation's if the question reaches back ('last time')."""
        if RECALL_EARLIER_WORDS.search(cmd):
            prev = self._get_previous_conversation_id()
            summary = self._get_or_generate_summary(prev) if prev is not None else None
            if summary:
                self.speak(f"Last time we spoke, {self.user_name}: {summary}")
            else:
                self.speak(f"I don't have an earlier conversation to recall, {self.user_name}.")
        else:
            self.summarise_conversation()

    # --------------------------------------------------------------
    #  TIME (IST from system clock)
    # --------------------------------------------------------------
    def _get_ist_time(self) -> datetime:
        """Get current time in IST from system clock."""
        # Windows system time is typically local, convert to IST
        try:
            # Get local time from system
            local_now = datetime.now()
            # Assume system is set to IST (Asia/Kolkata)
            ist = ZoneInfo("Asia/Kolkata")
            # If system timezone is different, we need to handle it
            # For now, assume system is in IST or user will set system time
            # Alternative: use UTC and convert
            utc_now = datetime.now(timezone.utc)
            ist_now = utc_now.astimezone(ist)
            return ist_now
        except Exception:
            # Fallback to local time
            return datetime.now()
 
    # --------------------------------------------------------------
    #  AUDIO MODELS
    # --------------------------------------------------------------
    def setup_audio_models(self):
        """Pre-load audio models for speed — GPU first, CPU fallback."""
        if whisper_available:
            print("Loading Whisper model...")
            try:
                self.whisper_model = WhisperModel(self.whisper_model_size, device="cuda", compute_type="float16")
                # Warm-up: missing cuBLAS/cuDNN DLLs only blow up on the FIRST
                # real inference, not when the model loads. Run one second of
                # silence now so a broken GPU falls back to CPU at startup
                # rather than on your first spoken command.
                import numpy as _np
                list(self.whisper_model.transcribe(
                    _np.zeros(self.sample_rate, dtype="float32"), beam_size=1, language="en"
                )[0])
                self.whisper_device = "cuda"
                print("Whisper ready (GPU).")
            except Exception as e:
                print(f"[Whisper GPU Error] {e}")
                print("Falling back to CPU...")
                try:
                    self.whisper_model = WhisperModel(self.whisper_model_size, device="cpu", compute_type="int8", cpu_threads=self._cpu_threads())
                    self.whisper_device = "cpu"
                    print("Whisper ready (CPU).")
                except Exception as e2:
                    print(f"[Whisper CPU Error] {e2}")
        if piper_available:
            model_path = os.path.join(os.path.dirname(__file__), "en_US-lessac-medium.onnx")
            if os.path.exists(model_path):
                self.piper_voice = PiperVoice.load(model_path)
                print("Piper TTS ready.")
        self._load_stop_model()
 
    # ==============================================================
    #  SPEECH ENGINE  (pipelined, non-blocking underneath, interruptible)
    #
    #  speak() hands text to two worker threads:
    #     synth thread : Piper text -> audio samples, in memory
    #     play thread  : feeds those samples to the sound card in ~23 ms blocks
    #  so the NEXT sentence is already synthesised while the current one is
    #  still playing (no gaps between sentences), and the LLM keeps generating
    #  while earlier sentences are being spoken.
    #
    #  While anything is queued or playing, a small monitor thread
    #  (_barge_in_loop) listens for a spoken interrupt. The moment you talk
    #  over Jupiter it pauses; if what it heard was "stop" it drops everything
    #  still queued, aborts the LLM stream, and the main loop goes straight
    #  back to listening for your next command.
    # ==============================================================
    @staticmethod
    def _cpu_threads() -> int:
        return max(2, min(8, os.cpu_count() or 4))

    def _init_speech_engine(self):
        self._tts_q = queue.Queue()            # (text, generation)
        self._play_q = queue.Queue()           # (kind, payload, rate, text, generation)
        self._speech_gen = 0                   # bumped on every interrupt; older items are dropped
        self._pending = 0                      # sentences queued or playing
        self._pending_cv = threading.Condition()
        self._interrupted = threading.Event()  # set by an interrupt, cleared when the next turn starts
        self._duck = threading.Event()         # "pause the audio, I think I hear you"
        self._playing = threading.Event()      # audio is coming out of the speakers right now
        self._speech_threads = []
        self._out_stream = None
        self._out_rate = None
        self._stream_failed = False
        self._native_proc = None
        self._syn_config = None
        self._barge_thread = None
        self._barge_stop = None
        self._stop_model = None

    def _ensure_speech_threads(self):
        if self._speech_threads:
            return
        self._speech_threads = [
            threading.Thread(target=self._synth_loop, name="jupiter-synth", daemon=True),
            threading.Thread(target=self._play_loop, name="jupiter-play", daemon=True),
        ]
        for t in self._speech_threads:
            t.start()

    def speak(self, text, wait: bool = True):
        """Say something. Blocks until it has been spoken (or you interrupted)
        unless wait=False, which just queues it and returns - think_stream()
        uses that so the model keeps generating while earlier sentences play.
        After an interrupt, speak() stays silent (it still prints) until the
        next turn starts, so the rest of a multi-line answer isn't read out."""
        print(f"JUPITER: {text}")
        self._last_response = text
        if not text or not str(text).strip():
            return
        if self._interrupted.is_set():
            return
        self._ensure_speech_threads()
        with self._pending_cv:
            self._pending += 1
            gen = self._speech_gen
        self._tts_q.put((str(text), gen))
        self._start_barge_monitor()
        if wait:
            self.wait_speech_done()

    def wait_speech_done(self):
        """Block until everything queued has been spoken, or dropped by an interrupt."""
        with self._pending_cv:
            while self._pending > 0:
                self._pending_cv.wait(timeout=0.25)
                if self._pending > 0 and self._speech_threads and not all(
                    t.is_alive() for t in self._speech_threads
                ):
                    self._pending = 0   # a worker died; don't hang the main loop
                    break

    def _speech_item_done(self):
        with self._pending_cv:
            self._pending = max(0, self._pending - 1)
            self._pending_cv.notify_all()

    def _discard_item(self, item):
        """Throw away a synthesised item that was interrupted before playing."""
        if item and item[0] == "wav":
            try:
                os.remove(item[1])
            except OSError:
                pass

    def _synth_loop(self):
        while True:
            text, gen = self._tts_q.get()
            try:
                if gen != self._speech_gen:
                    self._speech_item_done()
                    continue
                item = self._synthesize(text)
                if gen != self._speech_gen:
                    self._discard_item(item)
                    self._speech_item_done()
                    continue
                self._play_q.put((item[0], item[1], item[2], text, gen))
            except Exception as e:
                print(f"[TTS Error] {e}")
                self._speech_item_done()

    def _synthesize(self, text):
        """-> (kind, payload, rate). kind is "pcm" (int16 samples), "wav" (a temp
        file, the old route) or "text" (no Piper: use the OS voice)."""
        if piper_available and hasattr(self, "piper_voice"):
            try:
                if self._syn_config is None:
                    self._syn_config = SynthesisConfig(length_scale=0.85)
                if audio_input_available and self.tts_in_memory and not self._stream_failed:
                    buf = io.BytesIO()
                    with wave.open(buf, "wb") as wf:
                        self.piper_voice.synthesize_wav(text, wf, syn_config=self._syn_config)
                    buf.seek(0)
                    with wave.open(buf, "rb") as wf:
                        rate = wf.getframerate()
                        raw = wf.readframes(wf.getnframes())
                    return "pcm", np.frombuffer(raw, dtype=np.int16).copy(), rate
                path = self._tmp_wav_path()
                with wave.open(path, "wb") as wf:
                    self.piper_voice.synthesize_wav(text, wf, syn_config=self._syn_config)
                return "wav", path, None
            except Exception as e:
                print(f"[Piper Error] {e}")
        return "text", None, None

    def _tmp_wav_path(self) -> str:
        base = getattr(self, "data_dir", os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(base, f"tts_{os.getpid()}_{time.time_ns()}.wav")

    def _play_loop(self):
        while True:
            kind, payload, rate, text, gen = self._play_q.get()
            try:
                if gen != self._speech_gen:
                    self._discard_item((kind, payload))
                    continue
                self._playing.set()
                if kind == "pcm":
                    try:
                        self._play_pcm(payload, rate, gen)
                    except Exception as e:
                        # No output device / driver quirk: fall back to the old
                        # temp-wav route for this sentence and every later one.
                        print(f"[Audio Out Error] {e} - falling back to wav playback")
                        self._stream_failed = True
                        self._close_out_stream()
                        self._play_pcm_via_wav(payload, rate)
                elif kind == "wav":
                    try:
                        self._play_wav(payload)
                    finally:
                        try:
                            os.remove(payload)
                        except OSError:
                            pass
                else:
                    self._speak_native_fallback(text)
            except Exception as e:
                print(f"[TTS Play Error] {e}")
            finally:
                self._playing.clear()
                self._speech_item_done()

    def _get_out_stream(self, rate):
        if self._out_stream is not None and self._out_rate == rate:
            return self._out_stream
        self._close_out_stream()
        with _AUDIO_OPEN_LOCK:
            stream = sd.OutputStream(samplerate=rate, channels=1, dtype="int16", latency="low")
            stream.start()
        self._out_stream, self._out_rate = stream, rate
        return stream

    def _close_out_stream(self):
        stream, self._out_stream, self._out_rate = self._out_stream, None, None
        if stream is not None:
            try:
                stream.abort()
                stream.close()
            except Exception:
                pass

    def _play_pcm(self, pcm, rate, gen):
        """Feed samples to the sound card ~23 ms at a time, so an interrupt (or a
        "duck" while the stop-listener decides what it heard) takes effect almost
        immediately instead of after the whole sentence."""
        stream = self._get_out_stream(rate)
        block = 512
        n = len(pcm)
        i = 0
        while i < n:
            if gen != self._speech_gen:
                try:
                    stream.abort()    # drop whatever is still buffered...
                    stream.start()    # ...and be ready for the next thing to say
                except Exception:
                    self._close_out_stream()
                return
            if self._duck.is_set():
                t0 = time.monotonic()
                while self._duck.is_set() and gen == self._speech_gen and time.monotonic() - t0 < 4.0:
                    time.sleep(0.02)
                self._duck.clear()    # never leave it stuck on
                continue
            stream.write(pcm[i:i + block].reshape(-1, 1))
            i += block

    def _play_pcm_via_wav(self, pcm, rate):
        path = self._tmp_wav_path()
        try:
            with wave.open(path, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(rate)
                wf.writeframes(pcm.tobytes())
            self._play_wav(path)
        finally:
            try:
                os.remove(path)
            except OSError:
                pass

    def interrupt_speech(self):
        """Cut Jupiter off right now: bump the generation (the play thread
        notices within one 23 ms block and everything queued is dropped), kill
        any fallback TTS process, and flag the turn as interrupted so neither
        the rest of the answer nor the rest of the LLM stream gets spoken."""
        self._interrupted.set()
        with self._pending_cv:
            self._speech_gen += 1
        self._duck.clear()
        proc = self._native_proc
        if proc is not None:
            try:
                proc.terminate()
            except Exception:
                pass
        for q in (self._tts_q, self._play_q):
            while True:
                try:
                    item = q.get_nowait()
                except queue.Empty:
                    break
                if q is self._play_q:
                    self._discard_item(item)
                self._speech_item_done()

    # ----- spoken interrupt ("stop") ------------------------------------
    def _barge_ready(self) -> bool:
        return (
            self.barge_in_enabled
            and audio_input_available
            and self._voice_possible()
            and self.input_mode == "voice"
            and self.listen_mode == LISTEN_ACTIVE
        )

    def _start_barge_monitor(self):
        if not self._barge_ready():
            return
        t = self._barge_thread
        if t is not None and t.is_alive():
            return
        stop_evt = threading.Event()
        self._barge_stop = stop_evt
        self._barge_thread = threading.Thread(
            target=self._barge_in_loop, args=(stop_evt,), name="jupiter-barge-in", daemon=True
        )
        self._barge_thread.start()

    def _stop_barge_monitor(self):
        """Hand the mic back (called before the main loop opens its own stream)."""
        t, evt = self._barge_thread, self._barge_stop
        self._barge_thread = None
        if evt is not None:
            evt.set()
        if t is not None and t.is_alive() and t is not threading.current_thread():
            t.join(timeout=1.0)
        self._duck.clear()

    def _load_stop_model(self):
        """A tiny English-only Whisper on the CPU, used only to recognise the
        spoken interrupt. Loaded in the background so startup isn't slower;
        until it's ready (or if it can't be downloaded) the main model is used."""
        if not (whisper_available and hasattr(self, "whisper_model") and self.barge_in_enabled):
            return

        def _go():
            try:
                self._stop_model = WhisperModel("tiny.en", device="cpu", compute_type="int8", cpu_threads=2)
            except Exception as e:
                print(f"[Barge-in] tiny.en unavailable ({e}); using the main model to hear 'stop'.")

        threading.Thread(target=_go, name="jupiter-stop-model", daemon=True).start()

    def _transcribe_stop_clip(self, audio) -> str:
        model = self._stop_model or getattr(self, "whisper_model", None)
        if model is None:
            return ""
        try:
            x = self._clean_audio(audio.reshape(-1, 1)).reshape(-1)
            x = np.ascontiguousarray(x, dtype=np.float32)
            segments, _ = model.transcribe(
                x, beam_size=1, language="en", temperature=0.0, without_timestamps=True,
                condition_on_previous_text=False, vad_filter=False,
            )
            return " ".join(s.text for s in segments).strip()
        except Exception as e:
            print(f"[Barge-in STT Error] {e}")
            return ""

    def _is_interrupt_phrase(self, text: str) -> bool:
        """True if the clip ENDS in an interrupt phrase ("... stop", "stop it",
        "okay jupiter stop")."""
        words = re.findall(r"[a-z']+", text.lower().replace("\u2019", "'"))
        for n in (1, 2, 3):
            if len(words) >= n and INTERRUPT_PATTERN.match(" ".join(words[-n:])):
                return True
        return False

    def _barge_in_loop(self, stop_evt):
        """Runs only while Jupiter has something to say, and listens for you
        talking OVER the speakers:
          1. Jupiter's own voice leaks into the mic, so we measure how loud that
             leakage is (the loudest recent block) and only react to sound that
             is clearly louder - barge_in_ratio times louder.
          2. The moment that happens Jupiter pauses ("ducks"), which also keeps
             its voice out of the recording of yours.
          3. When you stop, the clip goes to a tiny CPU Whisper. If it ends in
             "stop" (see INTERRUPT_PATTERN) the speech is cut and the main loop
             starts listening; otherwise Jupiter just carries on where it was."""
        rate = self.sample_rate
        block = int(rate * 0.05)                      # 50 ms per read
        try:
            with _AUDIO_OPEN_LOCK:
                stream = sd.InputStream(samplerate=rate, channels=1, dtype="float32", blocksize=block)
                stream.start()
        except Exception as e:
            print(f"[Barge-in] couldn't open the mic ({e}); spoken interrupt is off.")
            self.barge_in_enabled = False
            return
        recent = []        # loudness of recent blocks while Jupiter talks = speaker leakage
        pre = []           # the last few blocks, so the clip includes the start of the word
        clip = None        # blocks of a possible interruption, once one starts
        loud = quiet = idle = false_alarms = 0
        floor = self.barge_in_min_rms
        try:
            while not stop_evt.is_set() and self._barge_ready():
                data, _ = stream.read(block)
                x = data.reshape(-1)
                rms = float(np.sqrt(np.mean(x.astype(np.float64) ** 2)))

                if self._pending <= 0 or self._interrupted.is_set():
                    # Nothing to interrupt. Give up after a second of that; the
                    # next speak() starts a fresh monitor.
                    recent.clear()
                    pre.clear()
                    clip = None
                    loud = quiet = 0
                    self._duck.clear()
                    idle += 1
                    if idle >= 20:
                        return
                    continue
                idle = 0

                if clip is None:
                    pre.append(x)
                    del pre[:-6]
                    leak = max(recent) if recent else 0.0
                    floor = max(self.barge_in_min_rms, leak * self.barge_in_ratio)
                    if self._playing.is_set() and len(recent) < 8:
                        recent.append(rms)            # first 0.4 s of speech: just learn the leakage level
                    elif rms > floor:
                        loud += 1
                        if loud >= 3:                 # ~150 ms of something louder than the leakage
                            clip = list(pre)
                            quiet = 0
                            self._duck.set()
                    else:
                        loud = 0
                        if self._playing.is_set():
                            recent.append(rms)
                            del recent[:-60]
                else:
                    clip.append(x)
                    quiet = 0 if rms > floor else quiet + 1
                    if quiet >= 6 or len(clip) >= 40:   # 300 ms of quiet, or a 2 s cap
                        heard = self._transcribe_stop_clip(np.concatenate(clip))
                        if heard and self._is_interrupt_phrase(heard):
                            print(f"[Interrupted] heard: {heard!r}")
                            self.interrupt_speech()
                            return
                        # Not "stop": carry on talking, and treat this loudness as
                        # speaker leakage so it doesn't trigger again.
                        recent.append(max(floor / self.barge_in_ratio, 0.01) * 1.4)
                        del recent[:-60]
                        false_alarms += 1
                        clip = None
                        loud = quiet = 0
                        pre.clear()
                        self._duck.clear()
                        if false_alarms >= 4:         # too noisy to be useful for this reply
                            return
        except Exception as e:
            print(f"[Barge-in Error] {e}")
        finally:
            self._duck.clear()
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass

    def _play_wav(self, path: str):
        """Play a wav file synchronously, one real command per OS — never a
        shell string, so there is nothing here for spoken/typed text to reach
        or influence.
 
        The previous version used subprocess.run(["start", path], shell=True)
        on non-Windows. That's broken twice over: "start" is a Windows cmd.exe
        builtin, not a program, and shell=True with a LIST argument doesn't do
        what it looks like — on POSIX only the first list item goes to the
        shell as the command string, and the rest become the shell's own
        positional parameters, not arguments to a command. So audio never
        actually played on Linux/macOS even though Piper had already
        generated a valid file. macOS gets its own path too, since
        aplay/paplay aren't reliably present there."""
        if sys.platform == "win32":
            # Plays synchronously, in-process — no external app window
            winsound.PlaySound(path, winsound.SND_FILENAME)
            return
        if sys.platform == "darwin":
            subprocess.run(["afplay", path], check=False, capture_output=True)
            return
        for player in ("paplay", "aplay", "ffplay"):
            if shutil.which(player):
                args = ([player, "-nodisp", "-autoexit", "-loglevel", "quiet", path]
                        if player == "ffplay" else [player, path])
                subprocess.run(args, check=False, capture_output=True)
                return
        print("[Audio Playback] No player found (tried paplay/aplay/ffplay). Text shown above.")
 
    def _run_tts_process(self, argv, timeout: float = 30.0):
        """Run an OS speech command we can KILL, so "stop" works here too."""
        proc = subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self._native_proc = proc
        try:
            deadline = time.monotonic() + timeout
            while proc.poll() is None:
                if self._interrupted.is_set() or time.monotonic() > deadline:
                    proc.terminate()
                    break
                time.sleep(0.03)
        finally:
            self._native_proc = None

    def _speak_native_fallback(self, text: str):
        """OS built-in TTS when Piper isn't available. Only ever runs a fixed
        argv list - the text is a separate array element (or, for PowerShell, a
        single-quoted string whose only special character, the quote, is
        doubled), never interpolated into a shell command line."""
        if sys.platform == "win32":
            try:
                safe_text = text.replace("'", "''")
                self._run_tts_process([
                    "powershell", "-NoProfile", "-Command",
                    "Add-Type -AssemblyName System.Speech; "
                    f"(New-Object System.Speech.Synthesis.SpeechSynthesizer).Speak('{safe_text}')"
                ])
                return
            except Exception as e:
                print(f"[Fallback TTS Error] {e}")
        elif sys.platform == "darwin":
            try:
                self._run_tts_process(["say", text])
                return
            except Exception as e:
                print(f"[Fallback TTS Error] {e}")
        else:
            for player in ("espeak-ng", "espeak", "spd-say"):
                if shutil.which(player):
                    try:
                        self._run_tts_process([player, text])
                        return
                    except Exception as e:
                        print(f"[Fallback TTS Error] {e}")
                    break
        print(f"[Text Only] {text}")

    # Stock phrases Whisper is well known to hallucinate out of silence or
    # background noise when it has nothing real to transcribe (common across
    # its training data — YouTube outro/caption boilerplate). If a whole
    # utterance is (near-)exactly one of these, it's almost certainly noise,
    # not something you said, and treating it as a command is what causes
    # Jupiter to "wake up on its own."
    _WHISPER_NOISE_HALLUCINATIONS = {
        "thank you", "thank you.", "thanks for watching", "thanks for watching!",
        "please subscribe", "subscribe", "bye", "bye.", "you", ".", "",
        "thank you for watching", "see you next time", "i'll see you next time",
        "the end", "okay", "ok", "um", "uh", "mm", "hmm",
    }
 
    def transcribe(self, audio, quick: bool = False, keep_short: bool = False):
        """Speech -> text with Whisper. `audio` is 16 kHz mono float32 straight
        from the mic (a numpy array - no temp file, nothing written to disk, and
        no ffmpeg decode step), or a file path.

        GPU library errors only surface on the first real transcription call
        (not at model load) - if that happens, reload Whisper on CPU
        automatically and retry once, instead of failing every turn.

        Language is FORCED (self.stt_language), not auto-detected - auto-detection
        is unreliable on short, code-switched clips. initial_prompt nudges the
        vocabulary toward your commands and proper nouns. Decoding is greedy-
        deterministic (temperature 0, no timestamps): Whisper's default
        "retry at a higher temperature" fallback is what turns a short command
        into a *different* wrong answer on every attempt, and it costs extra
        decode passes.

        Also screens out likely hallucinations (Whisper writes fluent text from
        silence/noise): segments with a high no_speech_prob, or text that is
        exactly one of Whisper's stock phrases, are discarded. keep_short=True
        (used for yes/no confirmations) lets a bare "okay" through, because that
        is a legitimate answer there."""
        if not whisper_available or not hasattr(self, 'whisper_model'):
            return ""

        audio_input = audio
        if getattr(audio, "ndim", None) is not None:
            # faster-whisper insists on a 1-D float32 array ("Input should be a
            # 1D array" is what a (N, 1) mic buffer gets you).
            audio_input = np.ascontiguousarray(audio.reshape(-1), dtype=np.float32)

        # Rebuilt each call so words you approved earlier in this session are
        # already biasing the very next transcription - no restart needed.
        # quick=True is the cheap pass used on standby: English, wake-word prompt.
        vocab_hint = "Jupiter. Hey Jupiter. Wake up, Jupiter." if quick else self._build_vocab_hint()
        # CPU (int8) is meaningfully slower per beam than GPU (float16), so drop
        # to greedy decoding there; GPU keeps the more accurate beam search.
        beam_size = 5 if (not quick and getattr(self, 'whisper_device', 'cuda') == 'cuda') else 1
        language = "en" if quick else self.stt_language
        noise = self._WHISPER_NOISE_HALLUCINATIONS
        if keep_short:
            noise = noise - {"okay", "ok"}

        def _run_transcribe():
            try:
                # No vad_filter: the recorder already trimmed the clip to the
                # speech (+ a little padding), and a second VAD pass can clip a
                # soft first syllable ("play" -> "lay").
                return self.whisper_model.transcribe(
                    audio_input, beam_size=beam_size, language=language,
                    initial_prompt=vocab_hint, condition_on_previous_text=False,
                    temperature=0.0, without_timestamps=True, vad_filter=False,
                )
            except TypeError:
                # An older faster-whisper without one of those options.
                return self.whisper_model.transcribe(
                    audio_input, beam_size=beam_size, language=language,
                    initial_prompt=vocab_hint,
                )

        def _extract(segments):
            segments = list(segments)
            if not segments:
                return ""
            # Whisper reports, per segment, how likely it thinks the audio was
            # actually silence/non-speech. A real command scores low across the
            # board; noise hallucinations tend to run high.
            no_speech = [getattr(s, "no_speech_prob", 0.0) for s in segments]
            avg_no_speech = sum(no_speech) / len(no_speech)
            text = " ".join(s.text for s in segments).strip()
            if avg_no_speech > 0.6:
                return ""
            if text.lower().strip(" .!?") in noise:
                return ""
            return text

        try:
            segments, info = _run_transcribe()
            return _extract(segments)
        except Exception as e:
            print(f"[STT Error] {e}")
            if getattr(self, 'whisper_device', 'cuda') == 'cuda':
                print("GPU inference failed - reloading Whisper on CPU...")
                try:
                    self.whisper_model = WhisperModel(self.whisper_model_size, device="cpu", compute_type="int8", cpu_threads=self._cpu_threads())
                    self.whisper_device = "cpu"
                    beam_size = 1
                    print("Whisper ready (CPU).")
                    segments, info = _run_transcribe()
                    return _extract(segments)
                except Exception as e2:
                    print(f"[STT CPU Fallback Error] {e2}")
            return ""

    def set_stt_language(self, lang_name: str):
        """Switch what language Whisper decodes into. 'english' keeps command
        words reliable (song/place names get transliterated phonetically);
        'hindi'/'marathi' decode natively in that script for real conversation."""
        code = self.STT_LANGUAGES.get(lang_name.lower())
        if code:
            self.stt_language = code
            self.speak(f"Switched to {lang_name.capitalize()} mode, sir.")
        else:
            self.speak(f"I don't have a mode for {lang_name}, sir.")
 
 
    def translate_text(self, text, target_lang="es"):
        """Translate using Argos Translate (primary) or AI fallback"""
        lang_map = {
            "spanish": "es", "french": "fr", "german": "de",
            "chinese": "zh", "japanese": "ja", "korean": "ko",
            "russian": "ru", "italian": "it", "portuguese": "pt"
        }
        target = lang_map.get(target_lang.lower(), target_lang)
 
        if translate_available:
            try:
                return argostranslate.translate.translate(text, "en", target)
            except Exception as e:
                print(f"[Argos Error] {e}")
 
        # Fallback: Use AI brain
        prompt = f"Translate to {target_lang}: {text}"
        return self.think(prompt)
 
    # --------------------------------------------------------------
    #  MEDIA / APPS / NAVIGATION  (all free — no paid API keys)
    # --------------------------------------------------------------
    def open_youtube(self, query: str = None):
        """Open YouTube, optionally with a search query. Free — just a URL."""
        try:
            if query:
                url = f"https://www.youtube.com/results?search_query={query.replace(' ', '+')}"
                webbrowser.open(url)
                self.speak(f"Searching YouTube for {query}, sir.")
            else:
                webbrowser.open("https://www.youtube.com")
                self.speak("Opening YouTube, sir.")
        except Exception as e:
            print(f"[YouTube Error] {e}")
            self.speak("I couldn't open YouTube, sir.")
 
    def _resolve_song_name(self, song_name: str) -> str:
        """Correct STT noise against your favorite songs before doing
        anything else. Whisper on short, unfamiliar titles ("High On You")
        commonly garbles them into something phonetically similar ("eye on
        you") — previously that garbled text was passed straight to YouTube
        search and played literally, with nothing checking whether it was
        actually close to a song you'd told Jupiter about.
 
        difflib.get_close_matches does simple sequence-similarity matching —
        no extra dependency, no network call, and cheap enough to run on
        every play command."""
        if not self.favorite_songs:
            return song_name
        match = difflib.get_close_matches(
            song_name.lower(),
            [s.lower() for s in self.favorite_songs],
            n=1, cutoff=0.5
        )
        if match:
            for original in self.favorite_songs:
                if original.lower() == match[0]:
                    return original
        return song_name
 
    def play_song(self, song_name: str):
        """Play a song: local Music folder first (offline, instant), then
        auto-play the top YouTube result via pywhatkit (free, no API key),
        then fall back to just opening YouTube search results."""
        song_name = song_name.strip()
        if not song_name:
            self.speak("What would you like me to play, sir?")
            return
 
        resolved = self._resolve_song_name(song_name)
        if resolved != song_name:
            print(f"[Song Match] Heard {song_name!r}, playing {resolved!r} instead.")
        song_name = resolved
 
        # 1. Local library — offline and free
        music_dir = os.path.join(os.path.expanduser("~"), "Music")
        if os.path.isdir(music_dir):
            try:
                candidates = [
                    f for f in os.listdir(music_dir)
                    if f.lower().endswith((".mp3", ".wav", ".flac", ".m4a"))
                ]
            except OSError:
                candidates = []
            song_lower = song_name.lower()
            # Exact substring match first (fast path, no ambiguity)
            exact = next((f for f in candidates if song_lower in f.lower()), None)
            # Otherwise fuzzy-match against filenames too — same STT-noise
            # problem can affect a locally-stored file name just as easily
            fname = exact or next(iter(difflib.get_close_matches(
                song_lower, [f.lower() for f in candidates], n=1, cutoff=0.5
            )), None)
            if fname and not exact:
                fname = next((f for f in candidates if f.lower() == fname), None)
            if fname:
                try:
                    os.startfile(os.path.join(music_dir, fname))
                    self.speak(f"Playing {fname} from your library, sir.")
                    return
                except Exception as e:
                    print(f"[Local Playback Error] {e}")
                    # fall through to YouTube
 
        # 2. YouTube autoplay (free, no key) — needs: pip install pywhatkit
        if pywhatkit_available:
            try:
                self.speak(f"Playing {song_name} on YouTube, sir.")
                pywhatkit.playonyt(song_name)
                return
            except Exception as e:
                print(f"[pywhatkit Error] {e}")
 
        # 3. Last resort — open search results, user clicks play
        self.open_youtube(song_name)
 
    def open_file_explorer(self, path: str = None):
        """Open Windows File Explorer, optionally at a specific folder."""
        try:
            if path and os.path.exists(path):
                subprocess.Popen(["explorer", path])
            else:
                subprocess.Popen(["explorer"])
            self.speak("Opening File Explorer, sir.")
        except Exception as e:
            print(f"[Explorer Error] {e}")
            self.speak("I couldn't open File Explorer, sir.")
 
    def open_app(self, app_name: str):
        """Launch a known app by name. SAFETY: never hands raw spoken/typed
        text to a shell — the known-app dict uses only fixed, hardcoded
        commands, and the fallback only launches something shutil.which
        actually resolves as a real executable already on PATH, and is never
        given any arguments. If it can't be resolved, we say so instead of
        guessing with a shell command.
 
        The shutil.which() fallback is deliberately generic (open anything
        installed), which means a misheard "open <system utility>" could
        resolve to a real admin tool already on PATH — e.g. Windows ships
        shutdown.exe, format.com and diskpart.exe as ordinary PATH
        executables. Launched with no arguments most of these just print
        usage text rather than doing anything, but that's not a guarantee
        worth relying on, so the small set of genuinely dangerous names is
        blocked outright rather than left to "probably harmless."
        """
        key = app_name.strip().lower()
        cmd = APP_COMMANDS.get(key)
 
        if not cmd and key in DANGEROUS_APP_NAMES:
            self.speak(f"I won't open {app_name}, sir — that's a system utility I keep off-limits by voice.")
            return
 
        try:
            if cmd:
                if cmd.startswith("start "):
                    # Fixed string from our own dict — never user input — safe with shell=True
                    subprocess.run(cmd, shell=True, check=False)
                else:
                    subprocess.Popen([cmd])
                self.speak(f"Opening {app_name}, sir.")
                return
 
            resolved = shutil.which(app_name)
            if resolved:
                subprocess.Popen([resolved])
                self.speak(f"Opening {app_name}, sir.")
            else:
                self.speak(
                    f"I don't recognize \"{app_name}\" as an app, sir. "
                    f"Add it to APP_COMMANDS if you'd like me to open it."
                )
        except Exception as e:
            print(f"[Open App Error] {e}")
            self.speak(f"I couldn't open {app_name}, sir.")
 
    # Nagpur's rough bounding box (left, top, right, bottom), used only to
    # softly bias ambiguous local queries ("collectorate office", "the mall")
    # toward Nagpur, without forcing every query into a "<place>, Nagpur,
    # India" string. The old version did the latter, so a genuinely different
    # city name like "Pune" got mangled into "Pune, Nagpur, India" and either
    # geocoded wrong or found nothing useful.
    _NAGPUR_VIEWBOX = "78.90,21.25,79.25,20.95"
 
    # Other major Indian cities: if the query names one of these directly,
    # don't bias toward Nagpur at all -- the user clearly means that city,
    # not a place inside Nagpur.
    _KNOWN_OTHER_CITIES = {
        "mumbai", "pune", "delhi", "new delhi", "bangalore", "bengaluru",
        "hyderabad", "chennai", "kolkata", "ahmedabad", "surat", "jaipur",
        "lucknow", "kanpur", "bhopal", "indore", "patna", "gurgaon",
        "gurugram", "noida", "chandigarh", "goa", "amritsar", "varanasi",
        "nashik", "aurangabad", "kolhapur", "solapur", "amravati", "wardha",
        "raipur", "jabalpur", "ranchi", "vadodara", "agra", "jodhpur",
        "udaipur", "shimla", "manali", "dehradun", "rishikesh", "guwahati",
        "bhubaneswar", "coimbatore", "kochi", "mysore", "mysuru", "visakhapatnam",
        "maharashtra", "gujarat", "karnataka", "kerala", "rajasthan", "punjab",
        "telangana", "madhya pradesh", "uttar pradesh", "bihar", "india",
        "london", "paris", "new york", "tokyo", "dubai", "singapore", "sydney",
        "berlin", "moscow", "beijing", "shanghai", "los angeles", "san francisco",
        "washington", "toronto", "bangkok", "kathmandu", "colombo", "dhaka",
        "karachi", "usa", "america", "uk", "china", "japan", "australia",
        "canada", "germany", "france",
    }

    _GEO_HEADERS = {"User-Agent": "JupiterAssistant/1.0 (personal use)"}

    def _names_other_place(self, place: str) -> bool:
        """True if the query already says where it is (Nagpur, a comma-separated
        city, or a well-known other city/state/country) -- then Nagpur-first
        would be wrong, so the query is searched as-is."""
        low = place.lower()
        return "nagpur" in low or "," in low or bool(self._other_place_re.search(low))

    def _nominatim(self, query: str, bounded=None):
        """One Nominatim search. bounded=True restricts results to Nagpur's
        bounding box, False only prefers it, None applies no bias at all."""
        params = {"q": query, "format": "json", "limit": 1}
        if bounded is not None:
            params["viewbox"] = self._NAGPUR_VIEWBOX
            params["bounded"] = 1 if bounded else 0
        resp = self.http.get(
            "https://nominatim.openstreetmap.org/search",
            params=params, headers=self._GEO_HEADERS, timeout=8
        )
        return resp.json()

    def _geocode_local_first(self, place: str):
        """Nagpur first, then everywhere else.

        1. Unless the query already names another place, search ONLY inside
           Nagpur's bounding box -- so "collectorate office" or "Sitabuldi
           fort" resolves to the Nagpur one, not a namesake in another state.
        2. If nothing is found there (or the query names somewhere else, like
           "Eiffel Tower" or "Pune"), search the rest of the world.

        Returns {"lat", "lon", "display", "local"} or None. Network errors
        propagate so each caller keeps its own error message. Results are
        cached for the session (it saves a round trip and respects
        Nominatim's one-request-per-second etiquette).
        """
        key = place.lower().strip()
        if key in self._geo_cache:
            return self._geo_cache[key]
        names_other = self._names_other_place(place)
        result = None
        if not names_other:
            hits = self._nominatim(place, bounded=True)
            if hits:
                result = {"lat": float(hits[0]["lat"]), "lon": float(hits[0]["lon"]),
                          "display": hits[0].get("display_name", place), "local": True}
        if result is None:
            hits = self._nominatim(place, bounded=None if names_other else False)
            if hits:
                result = {"lat": float(hits[0]["lat"]), "lon": float(hits[0]["lon"]),
                          "display": hits[0].get("display_name", place), "local": False}
        if result is not None:
            self._geo_cache[key] = result
        return result

    def find_location(self, place: str):
        """Speak the address (free OpenStreetMap Nominatim) and open Google
        Maps for the visual.

        Nagpur is searched FIRST (strictly inside the city), and only if
        nothing matches there does Jupiter search the rest of the world. A
        query that already names a place -- "Pune", "Taj Mahal, Agra" -- is
        searched as-is, so well-known places are never forced into Nagpur."""
        place = place.strip()
        if not place:
            self.speak("Which place should I look up, sir?")
            return

        maps_query = place
        try:
            found = self._geocode_local_first(place)
            if found and found["local"]:
                self.speak(f"{place} is in Nagpur, sir. It is located at {found['display']}.")
                maps_query = f"{place}, Nagpur"
            elif found:
                note = "" if self._names_other_place(place) else "I couldn't find that in Nagpur, so I searched elsewhere. "
                self.speak(f"{note}{place} is located at {found['display']}, sir.")
            else:
                self.speak(f"I couldn't find precise details for {place}, but here's the map, sir.")
        except Exception as e:
            print(f"[Geocode Error] {e}")
            self.speak(f"Opening the map for {place}, sir.")

        try:
            webbrowser.open(f"https://www.google.com/maps/search/?api=1&query={quote_plus(maps_query)}")
        except Exception as e:
            print(f"[Maps Error] {e}")

    # --------------------------------------------------------------
    #  SAFE MATH EVALUATION
    #  AST whitelist instead of eval() — parses to a syntax tree and only
    #  ever executes number literals, +-*/%**, unary +/-, and a small
    #  whitelist of math functions. There is no code path here that can
    #  reach attribute access, imports, or any other Python execution,
    #  unlike a restricted-builtins eval() which can sometimes be escaped.
    # --------------------------------------------------------------
    _SAFE_MATH_OPERATORS = {
        ast.Add: operator.add, ast.Sub: operator.sub,
        ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.Pow: operator.pow, ast.Mod: operator.mod,
        ast.USub: operator.neg, ast.UAdd: operator.pos,
    }
    _SAFE_MATH_FUNCS = {
        "sqrt": math.sqrt, "sin": math.sin, "cos": math.cos, "tan": math.tan,
        "log": math.log, "log10": math.log10, "abs": abs, "round": round,
        "pow": pow, "floor": math.floor, "ceil": math.ceil,
    }
 
    def _safe_eval_math(self, expr: str):
        node = ast.parse(expr, mode="eval").body
 
        def _eval(n):
            if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
                return n.value
            if isinstance(n, ast.BinOp) and type(n.op) in self._SAFE_MATH_OPERATORS:
                return self._SAFE_MATH_OPERATORS[type(n.op)](_eval(n.left), _eval(n.right))
            if isinstance(n, ast.UnaryOp) and type(n.op) in self._SAFE_MATH_OPERATORS:
                return self._SAFE_MATH_OPERATORS[type(n.op)](_eval(n.operand))
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in self._SAFE_MATH_FUNCS:
                return self._SAFE_MATH_FUNCS[n.func.id](*[_eval(a) for a in n.args])
            raise ValueError("Disallowed expression")
 
        return _eval(node)
 
    # --------------------------------------------------------------
    #  WEATHER — Open-Meteo (completely free, no API key, no signup)
    # --------------------------------------------------------------
    def get_weather(self, place: str = None):
        """Speak current temperature/wind for a place. Defaults to Nagpur.
        Read-only network calls to two free public APIs — nothing is
        written to disk or changed on your system."""
        place = (place or "Nagpur").strip()
        try:
            found = self._geocode_local_first(place)
            if not found:
                self.speak(f"I couldn't find {place}, sir.")
                return
            lat, lon = found["lat"], found["lon"]
 
            weather = requests.get(
                "https://api.open-meteo.com/v1/forecast",
                params={"latitude": lat, "longitude": lon, "current_weather": "true"},
                timeout=8
            ).json()
            current = weather.get("current_weather")
            if current:
                self.speak(
                    f"It's currently {current['temperature']}\u00b0C in {place}, sir, "
                    f"with wind speeds around {current['windspeed']} km/h."
                )
            else:
                self.speak(f"I couldn't fetch the weather for {place}, sir.")
        except Exception as e:
            print(f"[Weather Error] {e}")
            self.speak("I couldn't fetch the weather right now, sir.")
 
    # --------------------------------------------------------------
    #  BATTERY — read-only, via psutil (optional: pip install psutil)
    # --------------------------------------------------------------
    def get_battery_status(self):
        if not psutil_available:
            self.speak("Battery monitoring needs the psutil package, sir. Run: pip install psutil")
            return
        try:
            battery = psutil.sensors_battery()
            if battery is None:
                self.speak("I couldn't detect a battery on this system, sir.")
                return
            state = "and charging" if battery.power_plugged else "and not charging"
            self.speak(f"Battery is at {int(battery.percent)} percent, {state}, sir.")
        except Exception as e:
            print(f"[Battery Error] {e}")
            self.speak("I couldn't read the battery status, sir.")
 
    # --------------------------------------------------------------
    #  VOLUME — via pycaw (optional: pip install pycaw comtypes)
    #  Only ever adjusts the system volume level/mute state. Nothing here
    #  touches files, settings, or anything outside standard audio volume.
    # --------------------------------------------------------------
    def _get_endpoint_volume(self):
        """Return an IAudioEndpointVolume interface, whichever pycaw is installed.
 
        pip install pycaw currently installs one of two incompatible APIs
        depending on when it was installed:
          - classic (AndreMiras/pycaw): GetSpeakers() returns a raw COM
            IMMDevice pointer with .Activate(...).
          - newer maintained fork (amnweb/pycaw), now the default on PyPI:
            GetSpeakers() returns a pycaw-defined AudioDevice wrapper with a
            ready-made .EndpointVolume property instead, and no .Activate()
            at all — that mismatch is exactly what threw "'AudioDevice'
            object has no attribute 'Activate'". Try both so either
            installed version works.
        """
        devices = AudioUtilities.GetSpeakers()
        if hasattr(devices, "EndpointVolume"):
            return devices.EndpointVolume
        interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        return cast(interface, POINTER(IAudioEndpointVolume))
 
    def set_volume(self, direction: str = None, level: int = None):
        if not volume_control_available:
            self.speak("Volume control needs pycaw and comtypes, sir. Run: pip install pycaw comtypes")
            return
        try:
            volume = self._get_endpoint_volume()
 
            if direction == "mute":
                volume.SetMute(1, None)
                self.speak("Muted, sir.")
                return
            if direction == "unmute":
                volume.SetMute(0, None)
                self.speak("Unmuted, sir.")
                return
 
            current = volume.GetMasterVolumeLevelScalar()  # 0.0 - 1.0
            if level is not None:
                new_level = max(0.0, min(1.0, level / 100))
            elif direction == "up":
                new_level = min(1.0, current + 0.1)
            elif direction == "down":
                new_level = max(0.0, current - 0.1)
            else:
                new_level = current
 
            volume.SetMasterVolumeLevelScalar(new_level, None)
            self.speak(f"Volume set to {int(new_level * 100)} percent, sir.")
        except Exception as e:
            print(f"[Volume Error] {e}")
            self.speak("I couldn't adjust the volume, sir.")
 
    def _build_messages(self, user_input: str) -> dict:
        """Assemble the system prompt, recalled summaries and recent context
        into an Ollama message list. Shared by think() and think_stream() so
        the two can never drift apart.
 
        Returns {"messages": [...], "_prefix": str} where _prefix is a
        deterministic note to prepend when a requested recall wasn't found.
        """
        # Get conversation summary if exists
        summary = self._get_conversation_summary()
 
        system_prompt = f"""
You are JUPITER, a personal AI assistant having a spoken conversation with {self.user_name}.
 
IMPORTANT — how you fit into the system: real actions (playing music, opening
apps, setting timers/reminders, searching the web, checking weather,
translating, etc.) are handled by SEPARATE code that runs BEFORE you're ever
called. If a message has reached you at all, that means none of those direct
actions matched it — so you are NOT the thing that plays songs, opens
YouTube, or sets timers. Never say or imply that you just did one of those
things, and never invent details of an action "happening" (no "here's the
video", no "playing it now", no describing search results you didn't
actually retrieve). If the message looks like it was meant to trigger an
action but reached you instead, say plainly that you didn't catch it as a
command and ask the user to repeat it — don't perform an imaginary version of
it in words.
 
Speak naturally, like a real spoken reply — not a script. Never use stage
directions, asterisked actions, or narrate a scene (no "*plays the song*",
no "there it is!", no invented dialogue). Just answer directly, in your own
voice, as if you were talking.
 
Always address the user as "{self.user_name}" — never switch to any other title.
Be concise — this is speech, not an essay. A sentence or two is usually enough.
Never break character. Never say "As an AI language model".
"""
        # Add summary to system prompt if exists
        if summary:
            system_prompt += f"\n\nPrevious conversation summary:\n{summary}\n"
        facts = self._facts_for_prompt()
        if facts:
            system_prompt += (
                f"\n\nThings {self.user_name} has asked you to remember:\n{facts}\n"
                "Use them when relevant; do not recite them unprompted.\n"
            )
 
        # On-demand recall: only pull in a DIFFERENT conversation's summary if the
        # user explicitly asks for it in this message. Supports both:
        #   "use the summary of conversation 1 to answer this"  (specific number)
        #   "use the summary of the previous conversation..."   (relative)
        recall_requested = False
        recall_target_id = None
        specific_match = RECALL_SPECIFIC_PATTERN.search(user_input.lower())
        if specific_match:
            recall_requested = True
            num = specific_match.group(1) or specific_match.group(2)
            recall_target_id = int(num)
        elif RECALL_PREVIOUS_PATTERN.search(user_input.lower()):
            recall_requested = True
            recall_target_id = self._get_previous_conversation_id()
 
        recall_missing_note = None
        if recall_requested:
            recalled_summary = self._get_or_generate_summary(recall_target_id) if recall_target_id is not None else None
            if recalled_summary:
                system_prompt += (
                    f"\n\nThe user has asked you to recall an earlier, separate "
                    f"conversation (#{recall_target_id}). Its summary:\n{recalled_summary}\n"
                    f"Use it only to help answer the user's current message.\n"
                )
            else:
                # Don't rely on the model to notice/mention this on its own —
                # answer normally, but prefix the reply with a deterministic note.
                if recall_target_id is not None:
                    recall_missing_note = f"I don't have a conversation #{recall_target_id}, so I'm answering without that context. "
                else:
                    recall_missing_note = "There's no previous conversation to recall yet, so I'm answering without that context. "
 
        # Build message list: system + recent context + current user query
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(self._fetch_recent_context(limit=6))
        messages.append({"role": "user", "content": user_input})
        return {"messages": messages, "_prefix": recall_missing_note or ""}
 
    def think(self, user_input: str) -> str:
        """Send user input + recent conversation context to Ollama (blocking)."""
        built = self._build_messages(user_input)
        prefix = built["_prefix"]
        try:
            response = self.http.post(
                self.ollama_url,
                json={
                    "model": LLM_MODEL, "think": False,
                    "messages": built["messages"],
                    "stream": False,
                    "keep_alive": "30m",
                    "options": {"temperature": 0.7, "num_predict": 200}
                },
                timeout=(5, 60)
            )
            if response.status_code == 200:
                reply = response.json()["message"]["content"].strip()
                return (prefix + reply) if prefix else reply
            return f"Ollama error ({response.status_code}), {self.user_name}."
        except requests.exceptions.ConnectionError:
            return f"I'm offline, {self.user_name}. Ollama not running."
        except Exception as e:
            return f"Error: {str(e)[:50]}"
 
    def think_stream(self, user_input: str):
        """Same as think(), but queues each sentence for speech as the model
        produces it, so Jupiter starts talking after the first sentence and the
        model keeps generating while it speaks. A spoken "stop" aborts the
        stream (closing the connection makes Ollama stop generating).

        Falls back to the non-streaming path on ANY failure, so a streaming
        hiccup degrades to the old behaviour rather than losing the answer.
        """
        built = self._build_messages(user_input)
        prefix = built["_prefix"]

        spoken_any = False
        collected = []
        buffer = ""
        try:
            with self.http.post(
                self.ollama_url,
                json={
                    "model": LLM_MODEL, "think": False,
                    "messages": built["messages"],
                    "stream": True,
                    "keep_alive": "30m",
                    "options": {"temperature": 0.7, "num_predict": 200},
                },
                # (connect, read): a dead Ollama fails in ~5s instead of 60
                timeout=(5, 60),
                stream=True,
            ) as response:
                if response.status_code != 200:
                    raise RuntimeError(f"HTTP {response.status_code}")
                if prefix:
                    self.speak(prefix.strip(), wait=False)
                    spoken_any = True
                for line in response.iter_lines():
                    if self._interrupted.is_set():
                        break
                    if not line:
                        continue
                    try:
                        payload = json.loads(line)
                    except ValueError:
                        continue
                    piece = payload.get("message", {}).get("content", "")
                    if piece:
                        buffer += piece
                        collected.append(piece)
                    # Flush on sentence boundaries so Piper gets natural units.
                    # The first one goes out early (14+ chars) for a fast start.
                    while True:
                        match = re.search(r'[.!?](?:\s|$)', buffer)
                        if not match or match.end() < (14 if not spoken_any else 25):
                            break
                        sentence, buffer = buffer[:match.end()].strip(), buffer[match.end():]
                        if sentence:
                            self.speak(sentence, wait=False)
                            spoken_any = True
                    if payload.get("done"):
                        break
            if buffer.strip() and not self._interrupted.is_set():
                self.speak(buffer.strip(), wait=False)
                spoken_any = True
            self.wait_speech_done()
            full = prefix + "".join(collected)
            if (spoken_any or self._interrupted.is_set()) and full.strip():
                return full.strip()
            raise RuntimeError("empty stream")
        except Exception as e:
            print(f"[Streaming Error] {e}")
            self.wait_speech_done()
            if spoken_any or self._interrupted.is_set():
                # Already said something (or you cut it off) - don't repeat it
                return (prefix + "".join(collected)).strip() or "I lost my train of thought, sir."
            reply = self.think(user_input)
            self.speak(reply)
            return reply

    # ----- tidy what Whisper heard before the command patterns see it -----
    _NEEDS_ARGUMENT = {"play", "open", "search", "find", "call", "translate", "remind", "convert", "calculate"}
    _NUM_UNITS = {
        "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
        "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
        "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
    }
    _NUM_TENS = {
        "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
        "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
    }

    def _normalise_command(self, text: str) -> str:
        """The command patterns are anchored (^play, ^open, whole-phrase time/date),
        so one filler word or a polite wrapper used to send a perfectly good
        command to the LLM, which then improvised. This strips fillers and
        politeness ("um, could you please open notepad for me" -> "open
        notepad"), turns spoken numbers into digits for volume ("set volume to
        fifty"), and turns spoken arithmetic into a calculate command ("what is
        twelve times five"). The LLM still receives your original words - this
        only feeds the command matcher."""
        original = text.strip()
        t = FILLER_LEAD_PATTERN.sub("", original)
        t = POLITE_LEAD_PATTERN.sub("", t)
        stripped = POLITE_TAIL_PATTERN.sub("", t).strip()
        # "play thank you" is a song, not "play" + politeness
        if stripped and stripped.lower().split()[-1] not in self._NEEDS_ARGUMENT:
            t = stripped
        t = t.strip()
        if not t:
            return original
        if re.search(r"\bvolume\b", t, re.IGNORECASE):
            return self._spoken_numbers_to_digits(t)
        m = SPOKEN_MATH_PATTERN.match(t)
        if m:
            expr = self._spoken_math_expression(m.group(1))
            if expr:
                return f"calculate {expr}"
        return t

    def _spoken_numbers_to_digits(self, text: str) -> str:
        """'seventy five' -> '75', 'a hundred' -> '100'. 0-999 is plenty here."""
        units, tens = self._NUM_UNITS, self._NUM_TENS
        text = re.sub(r"\ba\s+hundred\b", "hundred", text, flags=re.IGNORECASE)
        tokens = text.split()

        def word(k):
            return tokens[k].lower().strip(".,!?")

        out = []
        i = 0
        while i < len(tokens):
            if word(i) in units or word(i) in tens or word(i) == "hundred":
                total = 0
                j = i
                while j < len(tokens):
                    w = word(j)
                    if w in units:
                        total += units[w]
                    elif w in tens:
                        total += tens[w]
                    elif w == "hundred":
                        total = max(total, 1) * 100
                    else:
                        break
                    j += 1
                out.append(str(total))
                i = j
            else:
                out.append(tokens[i])
                i += 1
        return " ".join(out)

    def _spoken_math_expression(self, spoken: str):
        """'twelve times five' -> '12 * 5'. None unless it is pure arithmetic."""
        s = self._spoken_numbers_to_digits(spoken.lower())
        for pattern, symbol in (
            (r"\bto the power of\b", " ** "),
            (r"\bmultiplied by\b|\btimes\b|\bx\b", " * "),
            (r"\bdivided by\b|\bover\b", " / "),
            (r"\bplus\b", " + "),
            (r"\bminus\b", " - "),
        ):
            s = re.sub(pattern, symbol, s)
        s = re.sub(r"\s+", " ", s).strip()
        if re.fullmatch(r"[\d\s+\-*/().%]+", s) and re.search(r"\d", s) and re.search(r"[+\-*/%]", s):
            return s
        return None

    def handle_action(self, command):
        """Execute practical tasks — returns True if handled"""
        cmd = command.lower().strip()
        # Set by meta-commands (mode switching, vocabulary management) so the
        # main loop doesn't offer to learn words from a command about words.
        self._skip_vocab = False

        # ----- Listening modes: sleep / push-to-talk / always listening ----
        # Anchored full-phrase patterns, so "how much sleep do I need" is
        # still a normal question. Checked first so nothing can swallow them.
        if SLEEP_MODE_PATTERN.match(cmd):
            self._skip_vocab = True
            self.enter_sleep_mode()
            return True
        if PTT_MODE_PATTERN.match(cmd):
            self._skip_vocab = True
            self.set_listen_mode(LISTEN_PTT)
            return True
        if ACTIVE_MODE_PATTERN.match(cmd):
            self._skip_vocab = True
            self.set_listen_mode(LISTEN_ACTIVE)
            return True

        # ----- Long-term memory and conversation recall --------------------
        fact_match = REMEMBER_FACT_PATTERN.match(command)
        if fact_match:
            self._skip_vocab = True
            self.remember_fact(fact_match.group(1))
            return True
        if RECALL_FACTS_PATTERN.search(cmd):
            self._skip_vocab = True
            self.recall_facts()
            return True
        if FORGET_FACTS_PATTERN.search(cmd):
            self._skip_vocab = True
            self.forget_facts()
            return True
        if WHAT_DISCUSSED_PATTERN.search(cmd):
            self._skip_vocab = True
            self.recall_discussion(cmd)
            return True
 
        # Time/Date (IST). The sun/moon guard matters because "what time is
        # sunrise" contains "time" and would otherwise just get the clock.
        if TIME_PATTERN.search(cmd) and not (SUN_PATTERN.search(cmd) or MOON_PATTERN.search(cmd)):
            now = self._get_ist_time()
            self.speak(f"It is {now.strftime('%I:%M %p')}, {self.user_name}.")
            return True
 
        if DATE_PATTERN.search(cmd):
            now = self._get_ist_time()
            self.speak(f"Today is {now.strftime('%A, %B %d, %Y')}, sir.")
            return True
 
        # Weather (defaults to Nagpur if no place given)
        weather_match = WEATHER_PATTERN.search(cmd)
        if weather_match:
            self.get_weather(weather_match.group(1))
            return True
 
        # Battery status
        if BATTERY_PATTERN.search(cmd):
            self.get_battery_status()
            return True
 
        # Volume control
        volume_set_match = VOLUME_SET_PATTERN.search(cmd)
        if volume_set_match:
            self.set_volume(level=int(volume_set_match.group(1)))
            return True
        if VOLUME_UP_PATTERN.search(cmd):
            self.set_volume(direction="up")
            return True
        if VOLUME_DOWN_PATTERN.search(cmd):
            self.set_volume(direction="down")
            return True
        if VOLUME_MUTE_PATTERN.match(cmd):
            self.set_volume(direction="mute")
            return True
        if VOLUME_UNMUTE_PATTERN.match(cmd):
            self.set_volume(direction="unmute")
            return True
 
        # ----- Timers and stopwatch ----------------------------------------
        # Before TIME_PATTERN would be wrong (it's earlier in this method), but
        # TIME_PATTERN uses \btime\b so "timer" never triggers it.
        timer_set = TIMER_SET_PATTERN.search(cmd)
        if timer_set:
            self._skip_vocab = True
            self.set_timer(timer_set.group(1))
            return True
 
        if TIMER_LIST_PATTERN.search(cmd):
            self._skip_vocab = True
            self.list_timers()
            return True
 
        if TIMER_CANCEL_PATTERN.search(cmd):
            self._skip_vocab = True
            self.cancel_timers()
            return True
 
        if STOPWATCH_START_PATTERN.search(cmd):
            self._skip_vocab = True
            self.start_stopwatch()
            return True
 
        if STOPWATCH_READ_PATTERN.search(cmd):
            self._skip_vocab = True
            self.read_stopwatch(stop=cmd.strip().startswith("stop"))
            return True
 
        # ----- Clipboard ----------------------------------------------------
        # Summarise is checked first: "summarise my clipboard" also matches the
        # plain read pattern's verb set in some phrasings.
        if CLIPBOARD_SUMMARISE_PATTERN.search(cmd):
            self._skip_vocab = True
            self.summarise_clipboard()
            return True
 
        if CLIPBOARD_READ_PATTERN.search(cmd):
            self._skip_vocab = True
            self.read_clipboard()
            return True
 
        if CLIPBOARD_COPY_PATTERN.search(cmd):
            self._skip_vocab = True
            self.copy_last_response()
            return True
 
        # ----- System / network --------------------------------------------
        if SYSTEM_STATS_PATTERN.search(cmd):
            self._skip_vocab = True
            self.get_system_stats()
            return True
 
        if WIFI_PATTERN.search(cmd):
            self._skip_vocab = True
            self.get_network_info()
            return True
 
        # ----- Conversion ---------------------------------------------------
        convert_match = CONVERT_PATTERN.search(cmd)
        if convert_match:
            self._skip_vocab = True
            self.convert_units(*convert_match.groups())
            return True
 
        # ----- Local documents ---------------------------------------------
        # Checked before the generic web search, or "search my documents for X"
        # would be sent to DuckDuckGo.
        doc_index_match = DOC_INDEX_PATTERN.search(cmd)
        if doc_index_match:
            self._skip_vocab = True
            self.index_documents(doc_index_match.group(1))
            return True
 
        if DOC_STATUS_PATTERN.search(cmd):
            self._skip_vocab = True
            self.document_status()
            return True
 
        doc_ask_match = DOC_ASK_PATTERN.search(command.strip())
        if doc_ask_match:
            self._skip_vocab = True
            self.ask_documents(doc_ask_match.group(1) or doc_ask_match.group(2) or "")
            return True
 
        # ----- Notes --------------------------------------------------------
        # Clear before read before add, so "clear my notes" isn't swallowed.
        if NOTE_CLEAR_PATTERN.search(cmd):
            self._skip_vocab = True
            self.clear_notes()
            return True
 
        if NOTE_READ_PATTERN.search(cmd):
            self._skip_vocab = True
            self.read_notes()
            return True
 
        note_add_match = NOTE_ADD_PATTERN.search(command.strip())
        if note_add_match:
            self.add_note(note_add_match.group(1))
            return True
 
        # ----- Sky ----------------------------------------------------------
        sun_match = SUN_PATTERN.search(cmd)
        if sun_match:
            self._skip_vocab = True
            self.get_sun_times(sun_match.group(1), sun_match.group(2))
            return True
 
        if MOON_PATTERN.search(cmd):
            self._skip_vocab = True
            self.get_moon_phase()
            return True
 
        # ----- News ---------------------------------------------------------
        news_match = NEWS_PATTERN.search(cmd)
        if news_match:
            self._skip_vocab = True
            self.get_news(news_match.group(1))
            return True
 
        # ----- Usage history ------------------------------------------------
        if HISTORY_STATS_PATTERN.search(cmd):
            self._skip_vocab = True
            self.show_usage_stats()
            return True
 
        # ----- Input mode (voice <-> text) ---------------------------------
        # Checked BEFORE the language-mode patterns so "text mode" is never
        # read as a language switch. These also set _skip_vocab so Jupiter
        # doesn't turn around and offer to learn its own control words.
        # Pin the keyboard open / restore one-shot typing. Must come before
        # TEXT_MODE_PATTERN, which "stay in text mode" also matches.
        if STICKY_TEXT_PATTERN.search(cmd):
            self._skip_vocab = True
            self.auto_return_to_voice = False
            self._save_setting("auto_return_to_voice", "0")
            self.set_input_mode("text", announce=False)
            self.speak("Staying in text mode, sir. Say auto voice when you want the mic back by default.")
            return True
 
        if AUTO_VOICE_PATTERN.search(cmd):
            self._skip_vocab = True
            self.auto_return_to_voice = True
            self._save_setting("auto_return_to_voice", "1")
            self.set_input_mode("voice", announce=False)
            self.speak("Back to voice, sir. Typed commands will be one-offs from now on.")
            return True
 
        if TEXT_MODE_PATTERN.search(cmd):
            self._skip_vocab = True
            self.set_input_mode("text")
            return True
 
        if VOICE_MODE_PATTERN.search(cmd):
            self._skip_vocab = True
            self.set_input_mode("voice")
            return True
 
        if WHICH_MODE_PATTERN.search(cmd):
            self._skip_vocab = True
            lang = next(
                (k for k, v in self.STT_LANGUAGES.items() if v == self.stt_language),
                self.stt_language
            )
            pin = "" if self.auto_return_to_voice else " Typing is pinned open."
            listen = {"active": "always listening", "push_to_talk": "push to talk",
                      "sleep": "standby"}.get(self.listen_mode, self.listen_mode)
            self.speak(f"{self.input_mode.capitalize()} input, {lang} speech, {listen}, sir.{pin}")
            return True
 
        # ----- Vocabulary management ---------------------------------------
        forget_match = VOCAB_FORGET_PATTERN.search(cmd)
        if forget_match:
            self._skip_vocab = True
            self.forget_vocabulary_word(forget_match.group(1))
            return True
 
        if VOCAB_SHOW_PATTERN.search(cmd):
            self._skip_vocab = True
            self.show_vocabulary()
            return True
 
        if VOCAB_ON_PATTERN.search(cmd):
            self._skip_vocab = True
            self.vocab_learning = True
            self._save_setting("vocab_learning", "1")
            self.speak("Vocabulary learning is on, sir. I'll ask before adding anything.")
            return True
 
        if VOCAB_OFF_PATTERN.search(cmd):
            self._skip_vocab = True
            self.vocab_learning = False
            self._save_setting("vocab_learning", "0")
            self.speak("Vocabulary learning is off, sir.")
            return True
 
        # Proactively teach a word/phrase (e.g. "remember the word Harry Potter")
        # instead of waiting for the auto-learn loop, which can't bootstrap on a
        # word Whisper has never once transcribed correctly to begin with.
        teach_match = TEACH_WORD_PATTERN.search(command)
        if teach_match:
            self._skip_vocab = True
            phrase = next(g for g in teach_match.groups() if g is not None).strip().rstrip(".!?")
            if phrase:
                self.add_vocabulary_word(phrase)
            return True
 
        # Switch STT language mode (english/hindi/marathi)
        lang_match = LANG_MODE_PATTERN.search(cmd)
        if lang_match:
            lang_name = lang_match.group(1) or lang_match.group(2)
            self.set_stt_language(lang_name)
            return True
 
        # Set how JUPITER addresses the user (persists across sessions)
        call_me_match = CALL_ME_PATTERN.search(cmd)
        if call_me_match:
            new_name = call_me_match.group(1).strip().rstrip(".!?")
            self.set_user_name(new_name)
            self.speak(f"Understood, {self.user_name}. I'll call you that from now on.")
            return True
 
        # Identity
        if IDENTITY_PATTERN.search(cmd):
            self.speak("I am JUPITER, your personal AI assistant, sir. Running entirely on this laptop.")
            return True
 
        # Calculation
        if CALCULATE_WORD_PATTERN.search(cmd) or CALCULATE_EXPR_PATTERN.match(cmd):
            try:
                expr = CALCULATE_WORD_PATTERN.sub("", cmd).replace("=", "").strip()
                # AST-whitelist evaluator — unlike eval(), this cannot execute
                # arbitrary Python even in principle: only numbers, +-*/%**,
                # unary +/-, and a small whitelist of math functions parse at all.
                result = self._safe_eval_math(expr)
                self.speak(f"The answer is {result}")
                return True
            except Exception:
                # Not a valid expression after all — fall through so other
                # patterns (or the LLM) get a chance at this command instead.
                pass
 
        # Search YouTube specifically (must be checked before generic Web Search
        # below, or "search X on youtube" would be sent to DuckDuckGo instead)
        youtube_search_match = YOUTUBE_SEARCH_PATTERN.search(cmd)
        if youtube_search_match:
            self.open_youtube(youtube_search_match.group(1).strip())
            return True
 
        # Location / directions must be checked before generic Web Search.
        # SEARCH_PATTERN also matches "find", so otherwise "find location of X"
        # would be treated as a web search.
        location_match = LOCATION_PATTERN.search(cmd)
        if location_match:
            self.find_location(location_match.group(1).strip())
            return True
 
        # Web Search
        search_match = SEARCH_PATTERN.search(cmd)
        if search_match:
            query = search_match.group(1).strip()
            if query:
                url = f"https://duckduckgo.com/html/?q={query.replace(' ', '+')}"
                webbrowser.open(url)  # already imported at module level
                self.speak(f"Searching for {query} on the web, sir.")
                return True
 
        # Translation
        if TRANSLATE_TRIGGER_PATTERN.search(cmd):
            # "translate hello to spanish"
            match = TRANSLATE_PARSE_PATTERN.search(cmd)
            if match:
                text, lang = match.groups()
                result = self.translate_text(text.strip(), lang)
                self.speak(f"In {lang}, that is: {result}")
                return True
            else:
                self.speak("Please say: translate [phrase] to [language]")
                return True
 
        # ----- Conversation Management -------------------------------------
        if NEW_CONV_WITH_SUMMARY_PATTERN.search(cmd):
            outgoing_conv_id = self.current_conv_id
 
            # Reuse an existing summary of the conversation we're leaving if one
            # exists (e.g. from an earlier "summarise"), otherwise generate one now.
            carried_summary = self._get_conversation_summary()
            if not carried_summary:
                outgoing_text = self._fetch_conversation_text(outgoing_conv_id)
                if outgoing_text:
                    carried_summary = self._call_summary_api(outgoing_text)
 
            initial_summary = (
                f"Carried over from a previous conversation: {carried_summary}"
                if carried_summary else None
            )
 
            now = self._get_ist_time().isoformat()
            with self._db_lock:
                if carried_summary:
                    self.conn.execute(
                        "UPDATE conversation_threads SET summary = ? WHERE conv_id = ?",
                        (carried_summary, outgoing_conv_id)
                    )
                cursor = self.conn.execute(
                    "INSERT INTO conversation_threads (created_at, summary) VALUES (?, ?)",
                    (now, initial_summary)
                )
                new_id = cursor.lastrowid
                self.current_conv_id = new_id
                self.conn.execute(
                    "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
                    ("last_conv_id", str(new_id))
                )
                self.conn.commit()
            if carried_summary:
                self.speak(f"Started new conversation #{new_id} with prior context carried over, {self.user_name}.")
            else:
                self.speak(f"Started new conversation #{new_id}, {self.user_name}. Nothing to carry over yet.")
            return True
 
        if NEW_CONV_PATTERN.search(cmd):
            now = self._get_ist_time().isoformat()
            with self._db_lock:
                cursor = self.conn.execute(
                    "INSERT INTO conversation_threads (created_at, summary) VALUES (?, ?)",
                    (now, None)
                )
                new_id = cursor.lastrowid
                self.current_conv_id = new_id
                self.conn.execute(
                    "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
                    ("last_conv_id", str(new_id))
                )
                self.conn.commit()
            self.speak(f"Started new conversation #{new_id}, {self.user_name}.")
            return True
 
        switch_match = SWITCH_CONV_PATTERN.search(cmd)
        if switch_match:
            self.set_current_conversation(int(switch_match.group(1)))
            return True
        if "switch" in cmd and "conversation" in cmd:
            # Had both keywords but no number — original fallback message
            self.speak("Usage: switch conversation <id>, sir.")
            return True
 
        if LIST_CONV_PATTERN.search(cmd):
            self.list_conversations()
            return True
 
        if CONTINUE_PATTERN.match(cmd):
            summary = self._get_conversation_summary()
            if summary:
                self.speak(f"Continuing conversation #{self.current_conv_id}, sir. Previous: {summary[:80]}...")
            else:
                self.speak(f"Continuing conversation #{self.current_conv_id}, sir.")
            return True
 
        # Summarise command
        if SUMMARISE_PATTERN.search(cmd):
            self.summarise_conversation()
            return True
 
        # Reminders
        remind_match = REMIND_PATTERN.search(cmd)
        if remind_match:
            task = remind_match.group(1).strip()
            self.add_reminder(task)
            return True
 
        # "remind me in 20 minutes to call Mom" — duration before the task.
        # Reorder to "call Mom in 20 minutes" so _parse_when's existing
        # "<task> in <duration>" logic picks up both correctly.
        remind_in_match = REMIND_IN_PATTERN.search(cmd)
        if remind_in_match:
            when_clause, task = remind_in_match.groups()
            self.add_reminder(f"{task.strip()} {when_clause.strip()}")
            return True
 
        if SHOW_REMINDERS_PATTERN.search(cmd):
            self.list_reminders()
            return True
 
        if CLEAR_REMINDERS_PATTERN.search(cmd):
            self.clear_reminders()
            return True
 
        # Open File
        open_file_match = OPEN_FILE_PATTERN.match(cmd)
        if open_file_match:
            path = open_file_match.group(1).strip()
            if os.path.exists(path):
                os.startfile(path)
                self.speak(f"Opening {path}, sir.")
            else:
                self.speak("File not found, sir.")
            return True
 
        # Open File Explorer
        if EXPLORER_PATTERN.match(cmd):
            self.open_file_explorer()
            return True
 
        # Open YouTube (no search term)
        if YOUTUBE_OPEN_PATTERN.match(cmd):
            self.open_youtube()
            return True
 
        # Play a song / media
        play_match = PLAY_PATTERN.match(cmd)
        if play_match:
            self.play_song(play_match.group(1).strip())
            return True
 
        # Open a generic application — checked last among "open ..." commands
        # so it doesn't shadow "open file", "open explorer", "open youtube" above
        open_app_match = OPEN_APP_PATTERN.match(cmd)
        if open_app_match:
            self.open_app(open_app_match.group(1).strip())
            return True
 
        # Shutdown
        if SHUTDOWN_PATTERN.match(cmd):
            self._skip_vocab = True
            self.speak(self._sign_off())
            self.is_running = False
            return True
 
        # Greeting — checked LAST among the direct-action patterns, not first.
        # GREETING_PATTERN matches "hello"/"hi"/"hey" anywhere in the string,
        # not just at the start, so it used to fire before Jupiter ever got to
        # check the more specific patterns — "translate hello to spanish" and
        # "search hello kitty toys" were both silently answered with a plain
        # greeting instead of doing what was actually asked, because GREETING
        # was checked earlier than TRANSLATE_TRIGGER_PATTERN/SEARCH_PATTERN.
        # Checking it last means every more specific command gets first
        # refusal, and a bare "hello" still falls through to here correctly
        # since nothing more specific matches it.
        greeting_match = GREETING_PATTERN.search(cmd)
        if greeting_match:
            word = greeting_match.group(1)
            if word.startswith("good"):
                self.speak(self._pick(TIMED_GREETING_REPLIES, greet=word.capitalize()))
            else:
                self.speak(self._pick(GREETING_REPLIES))
            return True
 
        return False  # Not a direct action → send to AI
 
 
    # ==============================================================
    #  TIMED EVENTS: reminders, timers, stopwatch
    #
    #  Design note on safety: the background thread NEVER speaks and never
    #  touches the microphone. It only checks what is due and drops it on a
    #  queue, which the main loop drains between turns. That keeps Piper's TTS
    #  and sounddevice's input stream single-threaded, which is what they
    #  expect — a thread calling speak() mid-recording would both talk over
    #  your command and get itself transcribed.
    # ==============================================================
    def start_scheduler(self):
        """Start the daemon thread that watches for due reminders and timers."""
        self._events = queue.Queue()
        self._timers = []          # list of dicts: {"label", "due", "seconds"}
        self._timers_lock = threading.Lock()  # guards _timers across threads
        self._stopwatch_start = None
        self._scheduler_stop = threading.Event()
        # _db_lock is created earlier, in setup_memory(), not here — see the
        # comment there for why.
        self._scheduler = threading.Thread(
            target=self._scheduler_loop, name="jupiter-scheduler", daemon=True
        )
        self._scheduler.start()
 
    def _scheduler_loop(self):
        """Poll every few seconds. Daemon thread, so it can never keep Python
        alive after you quit, and every iteration is wrapped so a transient DB
        or clock error can't kill the loop."""
        # 2 seconds is responsive enough for timers without being busy work:
        # one tiny indexed SQLite query per tick, which is far below noise.
        while not self._scheduler_stop.wait(2.0):
            try:
                now = self._get_ist_time()
 
                # Timers live in memory only — they're session-scoped by design
                with self._timers_lock:
                    due_timers = [t for t in self._timers if now >= t["due"]]
                    for t in due_timers:
                        self._timers.remove(t)
                for t in due_timers:
                    self._announce(f"Timer finished: {t['label']}.")
 
                # Reminders live in SQLite and survive restarts
                with self._db_lock:
                    rows = self.conn.execute(
                        "SELECT id, task FROM reminders "
                        "WHERE completed = 0 AND due_time IS NOT NULL AND due_time <= ?",
                        (now.isoformat(),)
                    ).fetchall()
                    for rid, task in rows:
                        self.conn.execute(
                            "UPDATE reminders SET completed = 1 WHERE id = ?", (rid,)
                        )
                    if rows:
                        self.conn.commit()
                for _, task in rows:
                    self._announce(f"Reminder, {self.user_name}: {task}.")
            except Exception as e:
                print(f"[Scheduler Error] {e}")
 
    def _announce(self, text: str):
        """Queue something for the main loop to speak, and print it right away
        so you see it even while Jupiter is blocked on input()."""
        print(f"\n[JUPITER] {text}")
        try:
            self._events.put_nowait(text)
        except Exception:
            pass
 
    def drain_events(self):
        """Speak anything the scheduler queued. Called by the main loop only."""
        while True:
            try:
                text = self._events.get_nowait()
            except queue.Empty:
                return
            except Exception:
                return
            self.speak(text)
 
    # ----- duration / time parsing (no external dependency required) -----
    def _words_to_digits(self, text: str) -> str:
        """Replace spoken number words ('one', 'thirty') with digits so
        DURATION_PATTERN's \\d+ can find them."""
        return NUMBER_WORD_PATTERN.sub(lambda m: str(NUMBER_WORDS[m.group(1).lower()]), text)
 
    def _parse_duration(self, text: str):
        """Turn '10 minutes', '1 hour 30 mins', '90s', or 'one minute' into
        seconds. Returns None if nothing duration-like is present."""
        total = 0
        found = False
        text = self._words_to_digits(text.lower())
        for amount, unit in DURATION_PATTERN.findall(text):
            mult = DURATION_UNITS.get(unit.rstrip("."), None)
            if mult is None:
                mult = DURATION_UNITS.get(unit.rstrip("s"), None)
            if mult is None:
                continue
            total += float(amount) * mult
            found = True
        if not found or total <= 0:
            return None
        # Sanity cap: 30 days. Anything longer is almost certainly a misparse.
        return min(total, 30 * 86400)
 
    def _parse_when(self, text: str):
        """Return (task_text, due_datetime_or_None) for a reminder phrase.
 
        Tries, in order: an explicit duration ('in 20 minutes'), a clock time
        ('at 6pm', 'at 18:30'), then dateparser if it happens to be installed.
        The built-in paths mean reminders work with zero extra packages.
        """
        raw = text.strip().rstrip(".!?")
        low = raw.lower()
        now = self._get_ist_time()
 
        # "... in 20 minutes" / "... after one minute"
        m = re.search(r'\b(?:in|after)\s+(.+)$', low)
        if m:
            seconds = self._parse_duration(m.group(1))
            if seconds:
                task = raw[:m.start()].strip().rstrip(",") or raw
                return task, now + timedelta(seconds=seconds)
 
        # "... at 6pm" / "... at 18:30" / "... tomorrow at 9am"
        m = re.search(r'\b(?:at|by)\s+(.+)$', low)
        if m:
            tail = m.group(1)
            clock = CLOCK_TIME_PATTERN.search(tail)
            if clock:
                if clock.group(3):                      # 12-hour with am/pm
                    hour = int(clock.group(1)) % 12
                    minute = int(clock.group(2) or 0)
                    if clock.group(3).replace(".", "").startswith("p"):
                        hour += 12
                else:                                    # 24-hour HH:MM
                    hour = int(clock.group(4))
                    minute = int(clock.group(5))
                if 0 <= hour <= 23 and 0 <= minute <= 59:
                    due = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                    if "tomorrow" in low:
                        due += timedelta(days=1)
                    elif due <= now:
                        due += timedelta(days=1)         # next occurrence
                    task = raw[:m.start()].strip().rstrip(",")
                    # Strip a trailing day word so the task reads "buy milk",
                    # not "buy milk tomorrow"
                    task = re.sub(r'\b(today|tonight|tomorrow)\s*$', '', task, flags=re.I).strip(" ,")
                    return (task or raw), due
 
        # Optional: let dateparser handle anything more exotic
        if dateparser_available:
            m = re.search(r'\b(?:at|by|on|in)\s+(.+)$', low)
            if m:
                try:
                    parsed = dateparser.parse(
                        m.group(1),
                        settings={
                            "PREFER_DATES_FROM": "future",
                            "TIMEZONE": "Asia/Kolkata",
                            "RETURN_AS_TIMEZONE_AWARE": True,
                        },
                    )
                    if parsed and parsed > now:
                        task = raw[:m.start()].strip().rstrip(",") or raw
                        return task, parsed
                except Exception as e:
                    print(f"[Dateparser Error] {e}")
 
        return raw, None
 
    def _humanise_delta(self, seconds: float) -> str:
        seconds = int(max(0, seconds))
        if seconds < 60:
            return f"{seconds} second{'s' if seconds != 1 else ''}"
        parts = []
        # Walk hour -> minute -> second so leftover seconds are announced too
        # instead of being silently dropped (90s used to read as "1 minute").
        for label, size in (("hour", 3600), ("minute", 60), ("second", 1)):
            if seconds >= size:
                value, seconds = divmod(seconds, size)
                parts.append(f"{value} {label}{'s' if value != 1 else ''}")
        if not parts:
            return "less than a second"
        if len(parts) == 1:
            return parts[0]
        return ", ".join(parts[:-1]) + " and " + parts[-1]
 
    # ----- timers -----
    def set_timer(self, phrase: str):
        seconds = self._parse_duration(phrase)
        if not seconds:
            self.speak(f"I couldn't work out a duration from that, {self.user_name}. Try: set a timer for 10 minutes.")
            return
        # Remove the duration itself, then a leading/trailing "for" as a WORD.
        # (An earlier version used strip(" ,.for"), which strips those
        # characters individually and turned "dinner" into "dinne".)
        label = DURATION_PATTERN.sub("", phrase)
        label = re.sub(r'^(?:\s*for\b)+|(?:\bfor\s*)+$', '', label).strip(" ,.")
        label = label or self._humanise_delta(seconds)
        with self._timers_lock:
            self._timers.append({
                "label": label,
                "due": self._get_ist_time() + timedelta(seconds=seconds),
                "seconds": seconds,
            })
        self.speak(f"Timer set for {self._humanise_delta(seconds)}, {self.user_name}.")
 
    def list_timers(self):
        with self._timers_lock:
            timers_snapshot = list(self._timers)
        if not timers_snapshot:
            self.speak(f"No timers running, {self.user_name}.")
            return
        now = self._get_ist_time()
        self.speak(f"{len(timers_snapshot)} timer(s) running, {self.user_name}:")
        for t in timers_snapshot:
            left = (t["due"] - now).total_seconds()
            self.speak(f"{t['label']}: {self._humanise_delta(left)} left.")
 
    def cancel_timers(self):
        with self._timers_lock:
            count = len(self._timers)
            self._timers.clear()
        if count:
            self.speak(f"Cancelled {count} timer(s), {self.user_name}.")
        else:
            self.speak(f"There were no timers to cancel, {self.user_name}.")
 
    # ----- stopwatch -----
    def start_stopwatch(self):
        self._stopwatch_start = time.monotonic()
        self.speak(f"Stopwatch started, {self.user_name}.")
 
    def read_stopwatch(self, stop: bool = False):
        if self._stopwatch_start is None:
            self.speak(f"The stopwatch isn't running, {self.user_name}.")
            return
        elapsed = time.monotonic() - self._stopwatch_start
        if stop:
            self._stopwatch_start = None
            self.speak(f"Stopped at {self._humanise_delta(elapsed)}, {self.user_name}.")
        else:
            self.speak(f"{self._humanise_delta(elapsed)} so far, {self.user_name}.")
 
    def add_reminder(self, phrase):
        """Store a reminder, with a real due time when one can be parsed.
 
        Previously due_time was always 'now' and nothing ever read it back, so
        reminders were write-only. Now an unparsed reminder is stored with a
        NULL due_time (it shows up in the list but never fires), and a timed
        one is picked up by the scheduler thread.
        """
        task, due = self._parse_when(phrase)
        with self._db_lock:
            self.conn.execute(
                "INSERT INTO reminders (task, due_time, created_time) VALUES (?, ?, ?)",
                (task, due.isoformat() if due else None, self._get_ist_time().isoformat())
            )
            self.conn.commit()
        if due:
            when = due.strftime("%I:%M %p on %b %d").lstrip("0")
            self.speak(f"Reminder set for {when}, {self.user_name}: {task}")
        else:
            self.speak(
                f"Noted, {self.user_name}: {task}. I couldn\'t pin a time to that, "
                f"so I\'ll keep it on the list rather than alert you. "
                f"Add \'in 20 minutes\' or \'at 6 pm\' if you want an alert."
            )
 
    def list_reminders(self):
        """List active reminders, newest due first, with their alert times."""
        with self._db_lock:
            rows = self.conn.execute(
                "SELECT task, due_time FROM reminders WHERE completed = 0 "
                "ORDER BY due_time IS NULL, due_time ASC"
            ).fetchall()
        if not rows:
            self.speak(f"No active reminders, {self.user_name}.")
            return
        self.speak(f"Your reminders, {self.user_name}:")
        for i, (task, due_time) in enumerate(rows, 1):
            if due_time:
                try:
                    when = datetime.fromisoformat(due_time).strftime("%I:%M %p on %b %d").lstrip("0")
                    self.speak(f"{i}. {task} — at {when}")
                    continue
                except ValueError:
                    pass
            self.speak(f"{i}. {task} — no alert time")
 
    def clear_reminders(self):
        """Mark all reminders complete. Rows are kept, not deleted, so nothing
        is ever irrecoverably lost from your own database."""
        with self._db_lock:
            cursor = self.conn.execute("UPDATE reminders SET completed=1 WHERE completed=0")
            self.conn.commit()
        self.speak(f"Cleared {cursor.rowcount} reminder(s), {self.user_name}.")
 
    def _read_text_input(self, prompt: str = "You: ") -> str:
        """Blocking keyboard read. Returns '' on EOF/interrupt rather than raising."""
        try:
            return input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            return ""
 
    def _pending_keyboard_input(self):
        """Non-blocking check for 'the user has started typing'.
 
        Returns None if the keyboard is idle, otherwise (text, is_complete):
          - Windows: characters already buffered, is_complete False — we echo
            them and let input() collect the rest of the line.
          - POSIX: the terminal is line-buffered, so anything available is a
            whole line already (press Enter to grab the turn), is_complete True.
        """
        try:
            if sys.platform == "win32":
                import msvcrt
                if not msvcrt.kbhit():
                    return None
                buf = ""
                first = True
                while msvcrt.kbhit():
                    ch = msvcrt.getwch()
                    if ch in ("\r", "\n"):
                        print()  # move off the echoed line before returning
                        return (buf, True)
                    if ch == "\x08":       # backspace
                        if buf:
                            buf = buf[:-1]
                            # Visually erase the character we just removed:
                            # move back, overwrite with a space, move back again.
                            print("\b \b", end="", flush=True)
                        continue
                    if ch == "\x03":       # Ctrl-C
                        raise KeyboardInterrupt
                    buf += ch
                    # getwch() reads the keystroke WITHOUT echoing it to the
                    # console (that's what getwche() is for) — the previous
                    # version only printed the whole buffered batch once,
                    # after this loop drained it, so anything typed was
                    # invisible until Jupiter happened to catch up. Echoing
                    # each character here, as it's consumed, is what actually
                    # shows you what you're typing.
                    if first:
                        print("You (typed): ", end="", flush=True)
                        first = False
                    print(ch, end="", flush=True)
                return (buf, False)
            else:
                import select
                if select.select([sys.stdin], [], [], 0)[0]:
                    return (sys.stdin.readline().rstrip("\n"), True)
                return None
        except KeyboardInterrupt:
            raise
        except Exception:
            return None
 
 
    # ==============================================================
    #  CLIPBOARD  (pyperclip — in-memory only, touches no files)
    # ==============================================================
    def _clipboard_text(self):
        if not pyperclip_available:
            self.speak(f"Clipboard access needs pyperclip, {self.user_name}. Run: pip install pyperclip")
            return None
        try:
            text = pyperclip.paste()
        except Exception as e:
            print(f"[Clipboard Error] {e}")
            self.speak(f"I couldn't read the clipboard, {self.user_name}.")
            return None
        if not text or not text.strip():
            self.speak(f"The clipboard is empty, {self.user_name}.")
            return None
        return text.strip()
 
    def read_clipboard(self, limit: int = 600):
        text = self._clipboard_text()
        if text is None:
            return
        if len(text) > limit:
            self.speak(f"The clipboard holds {len(text)} characters, {self.user_name}. The first part reads:")
            self.speak(text[:limit] + "...")
        else:
            self.speak(text)
 
    def summarise_clipboard(self):
        text = self._clipboard_text()
        if text is None:
            return
        # Keep the prompt bounded so a huge paste can't stall the local model
        excerpt = text[:6000]
        self.speak(f"Summarising {len(text)} characters, {self.user_name}. One moment.")
        summary = self._call_summary_api(excerpt)
        if summary:
            self.speak(summary)
        else:
            self.speak(f"I couldn't summarise that, {self.user_name}. Is Ollama running?")
 
    def copy_last_response(self):
        """Write Jupiter's last spoken line to the clipboard."""
        if not pyperclip_available:
            self.speak(f"Copying needs pyperclip, {self.user_name}. Run: pip install pyperclip")
            return
        last = getattr(self, "_last_response", "")
        if not last:
            self.speak(f"I haven't said anything worth copying yet, {self.user_name}.")
            return
        try:
            pyperclip.copy(last)
            self.speak(f"Copied to your clipboard, {self.user_name}.")
        except Exception as e:
            print(f"[Clipboard Error] {e}")
            self.speak(f"I couldn't write to the clipboard, {self.user_name}.")
 
    # ==============================================================
    #  SYSTEM STATS  (psutil — strictly read-only counters)
    #  Nothing here kills a process, changes a priority, or writes anything.
    # ==============================================================
    def get_system_stats(self):
        if not psutil_available:
            self.speak(f"System stats need psutil, {self.user_name}. Run: pip install psutil")
            return
        try:
            parts = []
            # interval=0.3 samples briefly; interval=None would report 0.0 on
            # the first call, which looks broken
            parts.append(f"CPU at {psutil.cpu_percent(interval=0.3):.0f} percent")
 
            mem = psutil.virtual_memory()
            parts.append(
                f"RAM at {mem.percent:.0f} percent, "
                f"{mem.available / 1073741824:.1f} gigabytes free"
            )
 
            drive = "C:\\" if sys.platform == "win32" else "/"
            try:
                disk = psutil.disk_usage(drive)
                parts.append(f"disk {disk.free / 1073741824:.0f} gigabytes free of {disk.total / 1073741824:.0f}")
            except Exception:
                pass
 
            try:
                uptime = time.time() - psutil.boot_time()
                parts.append(f"up for {self._humanise_delta(uptime)}")
            except Exception:
                pass
 
            self.speak(f"{', '.join(parts)}, {self.user_name}.")
        except Exception as e:
            print(f"[System Stats Error] {e}")
            self.speak(f"I couldn't read the system stats, {self.user_name}.")
 
    def get_network_info(self):
        """Report the connected WiFi network. On Windows this shells out to a
        read-only `netsh wlan show interfaces` query — a fixed argument list,
        no shell, no user text interpolated, and it changes nothing."""
        if sys.platform == "win32":
            try:
                out = subprocess.run(
                    ["netsh", "wlan", "show", "interfaces"],
                    capture_output=True, text=True, timeout=8, check=False
                ).stdout
                ssid = None
                signal = None
                for line in out.splitlines():
                    stripped = line.strip()
                    if stripped.lower().startswith("ssid") and ":" in stripped and "bssid" not in stripped.lower():
                        ssid = stripped.split(":", 1)[1].strip()
                    elif stripped.lower().startswith("signal") and ":" in stripped:
                        signal = stripped.split(":", 1)[1].strip()
                if ssid:
                    extra = f", signal {signal}" if signal else ""
                    self.speak(f"Connected to {ssid}{extra}, {self.user_name}.")
                    return
                self.speak(f"No WiFi network appears to be connected, {self.user_name}.")
                return
            except Exception as e:
                print(f"[Network Error] {e}")
 
        # Cross-platform fallback: just report whether interfaces are up
        if psutil_available:
            try:
                up = [n for n, s in psutil.net_if_stats().items() if s.isup and n.lower() != "lo"]
                if up:
                    self.speak(f"Active network interfaces: {', '.join(up)}, {self.user_name}.")
                    return
            except Exception as e:
                print(f"[Network Error] {e}")
        self.speak(f"I couldn't read the network status, {self.user_name}.")
 
    # ==============================================================
    #  UNIT + CURRENCY CONVERSION
    #  Units are fully offline. Currency uses the ECB's free Frankfurter API
    #  (no key, no signup), with a second free source as backup.
    # ==============================================================
    def convert_units(self, amount_text: str, src: str, dst: str):
        try:
            amount = float(amount_text.replace(",", ""))
        except ValueError:
            self.speak(f"I couldn't read that number, {self.user_name}.")
            return
 
        src_key = src.lower().strip(".")
        dst_key = dst.lower().strip(".")
 
        # Temperature first — it needs offsets, not just a ratio
        if src_key in TEMPERATURE_UNITS and dst_key in TEMPERATURE_UNITS:
            result = self._convert_temperature(amount, TEMPERATURE_UNITS[src_key], TEMPERATURE_UNITS[dst_key])
            self.speak(f"{self._fmt_number(amount)} {src} is {self._fmt_number(result)} {dst}, {self.user_name}.")
            return
 
        # Same-family unit conversion
        for family, units in UNIT_FAMILIES.items():
            if src_key in units and dst_key in units:
                result = amount * units[src_key] / units[dst_key]
                self.speak(f"{self._fmt_number(amount)} {src} is {self._fmt_number(result)} {dst}, {self.user_name}.")
                return
            if src_key in units or dst_key in units:
                # One side matched a family the other isn't in — say so rather
                # than silently falling through to a currency lookup
                other = dst if src_key in units else src
                self.speak(f"I can't convert {family} into {other}, {self.user_name}.")
                return
 
        # Currency
        src_code = CURRENCY_ALIASES.get(src_key, src_key.upper())
        dst_code = CURRENCY_ALIASES.get(dst_key, dst_key.upper())
        if src_code.lower() in CURRENCY_CODES and dst_code.lower() in CURRENCY_CODES:
            self.convert_currency(amount, src_code, dst_code)
            return
 
        self.speak(f"I don't know how to convert {src} to {dst}, {self.user_name}.")
 
    @staticmethod
    def _convert_temperature(value: float, src: str, dst: str) -> float:
        celsius = {"c": value, "f": (value - 32) * 5 / 9, "k": value - 273.15}[src]
        return {"c": celsius, "f": celsius * 9 / 5 + 32, "k": celsius + 273.15}[dst]
 
    @staticmethod
    def _fmt_number(value: float) -> str:
        """Trim float noise: 2.0 -> '2', 2.54000000001 -> '2.54'."""
        if abs(value) >= 1000:
            return f"{value:,.2f}".rstrip("0").rstrip(".")
        rounded = round(value, 4)
        return f"{rounded:g}"
 
    def convert_currency(self, amount: float, src: str, dst: str):
        if src == dst:
            self.speak(f"That's the same currency, {self.user_name}.")
            return
        rate = None
        # Frankfurter: European Central Bank data, free, no API key
        try:
            resp = requests.get(
                "https://api.frankfurter.app/latest",
                params={"amount": amount, "from": src, "to": dst},
                timeout=8
            )
            if resp.status_code == 200:
                data = resp.json()
                if dst in data.get("rates", {}):
                    converted = data["rates"][dst]
                    self.speak(f"{self._fmt_number(amount)} {src} is about {self._fmt_number(converted)} {dst}, {self.user_name}.")
                    return
        except Exception as e:
            print(f"[Currency Error] {e}")
 
        # Backup: open.er-api.com, also free and key-less
        try:
            resp = requests.get(f"https://open.er-api.com/v6/latest/{src}", timeout=8)
            if resp.status_code == 200:
                rate = resp.json().get("rates", {}).get(dst)
        except Exception as e:
            print(f"[Currency Fallback Error] {e}")
 
        if rate:
            self.speak(f"{self._fmt_number(amount)} {src} is about {self._fmt_number(amount * rate)} {dst}, {self.user_name}.")
        else:
            self.speak(f"I couldn't fetch an exchange rate for {src} to {dst}, {self.user_name}.")
 
 
    # ==============================================================
    #  NEWS  (RSS over plain HTTP — no key, no account, read-only)
    #  Parsed with the stdlib XML parser, so feedparser isn't required.
    # ==============================================================
    def get_news(self, topic: str = None, count: int = 5):
        topic_key = (topic or "top").strip().lower().rstrip("?.!")
        if topic_key in NEWS_FEEDS:
            url = NEWS_FEEDS[topic_key]
            label = topic_key
        else:
            url = NEWS_SEARCH_URL.format(q=requests.utils.quote(topic_key))
            label = topic_key
        try:
            resp = requests.get(url, timeout=10, headers={"User-Agent": "JupiterAssistant/1.0 (personal use)"})
            resp.raise_for_status()
            # defusedxml would be stricter, but this parses a fixed set of
            # known-good news feeds and never executes anything it reads.
            root = ET.fromstring(resp.content)
            items = root.findall(".//item")[:count]
            if not items:
                self.speak(f"No headlines came back for {label}, {self.user_name}.")
                return
            self.speak(f"Top {len(items)} headlines for {label}, {self.user_name}:")
            for i, item in enumerate(items, 1):
                title = (item.findtext("title") or "").strip()
                if not title:
                    continue
                # Google News appends " - Publisher"; keep it, it's useful
                self.speak(f"{i}. {title}")
        except requests.RequestException as e:
            print(f"[News Error] {e}")
            self.speak(f"I couldn't reach the news feed, {self.user_name}.")
        except ET.ParseError as e:
            print(f"[News Parse Error] {e}")
            self.speak(f"The news feed came back in a format I couldn't read, {self.user_name}.")
 
    # ==============================================================
    #  SKY: sunrise / sunset (Open-Meteo, free) and moon phase (local maths)
    # ==============================================================
    def _geocode(self, place: str):
        """Return (lat, lon, display_name), Nagpur first then elsewhere."""
        try:
            found = self._geocode_local_first(place)
            if found:
                return found["lat"], found["lon"], found["display"]
        except Exception as e:
            print(f"[Geocode Error] {e}")
        return None

    def get_sun_times(self, which: str = "sunrise", place: str = None):
        place = (place or "Nagpur").strip().rstrip("?.!")
        geo = self._geocode(place)
        if not geo:
            self.speak(f"I couldn't find {place}, {self.user_name}.")
            return
        lat, lon, _ = geo
        try:
            data = requests.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": lat, "longitude": lon,
                    "daily": "sunrise,sunset", "timezone": "auto", "forecast_days": 1,
                },
                timeout=8
            ).json()
            daily = data.get("daily", {})
            rise = (daily.get("sunrise") or [None])[0]
            setting = (daily.get("sunset") or [None])[0]
            if not rise or not setting:
                self.speak(f"I couldn't fetch sun times for {place}, {self.user_name}.")
                return
            rise_t = datetime.fromisoformat(rise).strftime("%I:%M %p").lstrip("0")
            set_t = datetime.fromisoformat(setting).strftime("%I:%M %p").lstrip("0")
            if which == "sunset":
                self.speak(f"Sunset in {place} is at {set_t} today, {self.user_name}. Sunrise was {rise_t}.")
            else:
                self.speak(f"Sunrise in {place} is at {rise_t} today, {self.user_name}. Sunset is at {set_t}.")
        except Exception as e:
            print(f"[Sun Times Error] {e}")
            self.speak(f"I couldn't fetch sun times right now, {self.user_name}.")
 
    def get_moon_phase(self):
        """Computed locally from the synodic month — no network at all.
        Accurate to roughly a few hours, which is far more than enough to name
        the phase."""
        try:
            now = self._get_ist_time()
            known_new_moon = datetime(2000, 1, 6, 18, 14, tzinfo=timezone.utc)
            if now.tzinfo is None:
                now = now.replace(tzinfo=timezone.utc)
            synodic = 29.530588853
            days = (now - known_new_moon).total_seconds() / 86400.0
            age = days % synodic
            fraction = age / synodic
            illumination = (1 - math.cos(2 * math.pi * fraction)) / 2
 
            names = [
                (0.0625, "new moon"), (0.1875, "waxing crescent"), (0.3125, "first quarter"),
                (0.4375, "waxing gibbous"), (0.5625, "full moon"), (0.6875, "waning gibbous"),
                (0.8125, "last quarter"), (0.9375, "waning crescent"), (1.01, "new moon"),
            ]
            phase = next(name for threshold, name in names if fraction < threshold)
            self.speak(
                f"It's a {phase}, {self.user_name}. About {illumination * 100:.0f} percent illuminated, "
                f"{age:.1f} days into the cycle."
            )
        except Exception as e:
            print(f"[Moon Phase Error] {e}")
            self.speak(f"I couldn't work out the moon phase, {self.user_name}.")
 
    # ==============================================================
    #  NOTES  (a plain Markdown file inside Jupiter's own data folder)
    #  Never writes anywhere else, and "clear my notes" archives rather than
    #  deletes, so a misheard command can't destroy anything.
    # ==============================================================
    def _notes_path(self) -> str:
        return os.path.join(self.data_dir, "notes.md")
 
    def add_note(self, text: str):
        text = text.strip().rstrip(".")
        if not text:
            self.speak(f"What should I note down, {self.user_name}?")
            return
        try:
            stamp = self._get_ist_time().strftime("%Y-%m-%d %H:%M")
            with open(self._notes_path(), "a", encoding="utf-8") as f:
                f.write(f"- [{stamp}] {text}\n")
            self.speak(f"Noted, {self.user_name}.")
        except OSError as e:
            print(f"[Notes Error] {e}")
            self.speak(f"I couldn't write that note, {self.user_name}.")
 
    def read_notes(self, count: int = 10):
        path = self._notes_path()
        if not os.path.exists(path):
            self.speak(f"You haven't saved any notes yet, {self.user_name}.")
            return
        try:
            with open(path, encoding="utf-8") as f:
                lines = [l.strip() for l in f if l.strip()]
        except OSError as e:
            print(f"[Notes Error] {e}")
            self.speak(f"I couldn't read your notes, {self.user_name}.")
            return
        if not lines:
            self.speak(f"Your notes file is empty, {self.user_name}.")
            return
        recent = lines[-count:]
        self.speak(f"Your {len(recent)} most recent note(s), {self.user_name}:")
        for line in recent:
            # Strip the "- [timestamp] " prefix when speaking it back
            self.speak(re.sub(r'^-\s*\[[^\]]*\]\s*', '', line))
 
    def clear_notes(self):
        """Archive rather than delete. The old notes are renamed with a
        timestamp so nothing is ever actually destroyed by a voice command."""
        path = self._notes_path()
        if not os.path.exists(path):
            self.speak(f"There are no notes to clear, {self.user_name}.")
            return
        confirmed = self.ask_yes_no(f"Archive all your notes, {self.user_name}?")
        if confirmed is not True:
            self.speak(f"Leaving your notes alone, {self.user_name}.")
            return
        try:
            stamp = self._get_ist_time().strftime("%Y%m%d-%H%M%S")
            archive = os.path.join(self.data_dir, f"notes-{stamp}.md")
            os.rename(path, archive)
            self.speak(f"Notes archived, {self.user_name}. The old file is still in your data folder.")
        except OSError as e:
            print(f"[Notes Error] {e}")
            self.speak(f"I couldn't archive your notes, {self.user_name}.")
 
    # ==============================================================
    #  LOCAL DOCUMENT Q&A
    #  Embeds plain-text files with the Ollama model you're already running,
    #  stores the vectors in Jupiter's own SQLite DB, and answers questions
    #  from them. Entirely offline and READ-ONLY on your documents — Jupiter
    #  opens them with mode 'r' and never writes, moves or deletes anything.
    # ==============================================================
    def _embed(self, text: str):
        """Return an embedding vector from Ollama, or None on any failure."""
        try:
            resp = requests.post(
                self.ollama_url.replace("/api/chat", "/api/embeddings"),
                json={"model": DOC_EMBED_MODEL, "prompt": text[:8000]},
                timeout=(5, 60)
            )
            if resp.status_code == 200:
                vec = resp.json().get("embedding")
                if vec:
                    return vec
            else:
                print(f"[Embed Error] HTTP {resp.status_code}")
        except Exception as e:
            print(f"[Embed Error] {e}")
        return None
 
    @staticmethod
    def _chunk_text(text: str):
        """Split into overlapping windows so a sentence spanning a boundary
        still lands intact in at least one chunk."""
        chunks = []
        step = max(1, DOC_CHUNK_CHARS - DOC_CHUNK_OVERLAP)
        for start in range(0, len(text), step):
            chunk = text[start:start + DOC_CHUNK_CHARS].strip()
            if len(chunk) > 40:
                chunks.append(chunk)
            if start + DOC_CHUNK_CHARS >= len(text):
                break
        return chunks
 
    @staticmethod
    def _pack_vector(vec):
        return struct.pack(f"<{len(vec)}f", *vec)
 
    @staticmethod
    def _unpack_vector(blob):
        return struct.unpack(f"<{len(blob) // 4}f", blob)
 
    @staticmethod
    def _cosine(a, b):
        if len(a) != len(b):
            return -1.0
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(y * y for y in b))
        if na == 0 or nb == 0:
            return -1.0
        return dot / (na * nb)
 
    def index_documents(self, folder: str = None):
        """Read plain-text files under a folder and store their embeddings.
        Hard-capped at DOC_MAX_FILES files and DOC_MAX_FILE_BYTES each, so
        pointing it at the wrong directory wastes a little time, not your
        whole evening."""
        folder = (folder or "").strip().strip('"').rstrip("?.!")
        if not folder:
            folder = os.path.join(os.path.expanduser("~"), "Documents")
        folder = os.path.expanduser(folder)
 
        if not os.path.isdir(folder):
            self.speak(f"I can't find the folder {folder}, {self.user_name}.")
            return
 
        files = []
        for root, dirs, names in os.walk(folder):
            # Skip hidden and dependency directories — nothing useful, lots of files
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in
                       ("node_modules", "__pycache__", "venv", ".venv", "site-packages")]
            for name in names:
                if name.lower().endswith(DOC_EXTENSIONS):
                    path = os.path.join(root, name)
                    try:
                        if os.path.getsize(path) <= DOC_MAX_FILE_BYTES:
                            files.append(path)
                    except OSError:
                        continue
                if len(files) >= DOC_MAX_FILES:
                    break
            if len(files) >= DOC_MAX_FILES:
                break
 
        if not files:
            self.speak(f"I found no readable text files under {folder}, {self.user_name}.")
            return
 
        self.speak(f"Indexing {len(files)} file(s), {self.user_name}. This runs locally and may take a minute.")
 
        # Probe the embedding model once before doing the work
        if self._embed("probe") is None:
            self.speak(
                f"I couldn't reach the embedding model, {self.user_name}. "
                f"Run: ollama pull {DOC_EMBED_MODEL}"
            )
            return
 
        indexed = 0
        chunks_total = 0
        for path in files:
            try:
                with open(path, encoding="utf-8", errors="ignore") as f:
                    content = f.read()
            except OSError as e:
                print(f"[Index Skip] {path}: {e}")
                continue
            if not content.strip():
                continue
 
            mtime = str(os.path.getmtime(path))
            with self._db_lock:
                existing = self.conn.execute(
                    "SELECT mtime FROM documents WHERE path = ? LIMIT 1", (path,)
                ).fetchone()
            if existing and existing[0] == mtime:
                continue  # unchanged since last index
 
            chunks = self._chunk_text(content)
            embedded_chunks = []
            embedding_failed = False
 
            for i, chunk in enumerate(chunks):
                vec = self._embed(chunk)
                if vec is None:
                    embedding_failed = True
                    print(f"[Index Skip] {path}: embedding failed for chunk {i + 1}/{len(chunks)}")
                    break
                embedded_chunks.append((i, chunk, vec))
 
            # Replace the old index only after every chunk succeeds.
            if embedding_failed:
                continue
 
            with self._db_lock:
                self.conn.execute("DELETE FROM documents WHERE path = ?", (path,))
                indexed_at = self._get_ist_time().isoformat()
                for i, chunk, vec in embedded_chunks:
                    self.conn.execute(
                        "INSERT INTO documents (path, chunk_index, text, embedding, mtime, indexed_at) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (path, i, chunk, self._pack_vector(vec), mtime, indexed_at)
                    )
                self.conn.commit()
 
            chunks_total += len(embedded_chunks)
            indexed += 1
            print(f"  indexed {os.path.basename(path)}")
 
        self._save_setting("doc_folder", folder)
        self.speak(f"Indexed {indexed} file(s) into {chunks_total} chunk(s), {self.user_name}.")
 
    def ask_documents(self, question: str, top_k: int = 4):
        question = question.strip().rstrip("?.!")
        if not question:
            self.speak(f"What should I look for, {self.user_name}?")
            return
        with self._db_lock:
            rows = self.conn.execute("SELECT path, text, embedding FROM documents").fetchall()
        if not rows:
            self.speak(
                f"I haven't indexed any documents yet, {self.user_name}. "
                f"Say: index my documents at, then the folder path."
            )
            return
 
        q_vec = self._embed(question)
        if q_vec is None:
            self.speak(f"I couldn't embed that question, {self.user_name}. Is Ollama running?")
            return
 
        scored = []
        for path, text, blob in rows:
            try:
                score = self._cosine(q_vec, self._unpack_vector(blob))
            except Exception:
                continue
            scored.append((score, path, text))
        scored.sort(reverse=True, key=lambda x: x[0])
        best = [s for s in scored[:top_k] if s[0] > 0.2]
 
        if not best:
            self.speak(f"Nothing in your documents looked relevant, {self.user_name}.")
            return
 
        context = "\n\n---\n\n".join(
            f"From {os.path.basename(p)}:\n{t}" for _, p, t in best
        )
        prompt = (
            f"Answer the question using ONLY the excerpts below. If they don't "
            f"contain the answer, say so plainly.\n\n{context}\n\nQuestion: {question}"
        )
        try:
            resp = requests.post(
                self.ollama_url,
                json={
                    "model": LLM_MODEL, "think": False,
                    "messages": [
                        {"role": "system", "content": "You answer strictly from the provided excerpts."},
                        {"role": "user", "content": prompt},
                    ],
                    "stream": False,
                    "options": {"temperature": 0.2, "num_predict": 250},
                },
                timeout=(5, 60)
            )
            if resp.status_code == 200:
                answer = resp.json()["message"]["content"].strip()
                sources = ", ".join(sorted({os.path.basename(p) for _, p, _ in best}))
                self.speak(answer)
                self.speak(f"Source: {sources}.")
            else:
                self.speak(f"Ollama returned an error, {self.user_name}.")
        except Exception as e:
            print(f"[Doc Q&A Error] {e}")
            self.speak(f"I couldn't answer from your documents, {self.user_name}.")
 
    def document_status(self):
        with self._db_lock:
            row = self.conn.execute(
                "SELECT COUNT(DISTINCT path), COUNT(*) FROM documents"
            ).fetchone()
            folder = self.conn.execute(
                "SELECT value FROM metadata WHERE key = 'doc_folder'"
            ).fetchone()
        if not row or not row[0]:
            self.speak(f"No documents are indexed, {self.user_name}.")
            return
        where = f" from {folder[0]}" if folder else ""
        self.speak(f"{row[0]} file(s) indexed{where}, {row[1]} chunk(s) total, {self.user_name}.")
 
    # ==============================================================
    #  USAGE HISTORY  (reads your own conversations table, nothing else)
    # ==============================================================
    def show_usage_stats(self, days: int = 7):
        since = (self._get_ist_time() - timedelta(days=days)).isoformat()
        with self._db_lock:
            rows = self.conn.execute(
                "SELECT message FROM conversations WHERE role = 'user' AND timestamp >= ?",
                (since,)
            ).fetchall()
        if not rows:
            self.speak(f"No commands recorded in the last {days} days, {self.user_name}.")
            return
 
        counts = {}
        for (message,) in rows:
            # Bucket by first meaningful word — a rough but honest proxy for
            # "what kind of thing did I ask for"
            words = [w for w in WORD_TOKEN_PATTERN.findall(message.lower()) if len(w) > 2]
            if not words:
                continue
            counts[words[0]] = counts.get(words[0], 0) + 1
 
        top = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:5]
        self.speak(f"{len(rows)} command(s) in the last {days} days, {self.user_name}. Most common openers:")
        for word, count in top:
            self.speak(f"{word}: {count} time(s)")
 
    def listen_for_command(self):
        """Get one command in the current input mode.
 
        Typing is ONE-SHOT by default: whenever a turn comes from the keyboard,
        Jupiter flips straight back to the microphone for the next turn. So you
        type when you want to, speak the rest of the time, and never have to
        announce either. "stay in text mode" pins the keyboard open; "auto
        voice" restores the one-shot behaviour.
 
          voice mode -> just start typing. Jupiter notices keys in the buffer
                        before it opens the mic and takes that turn from the
                        keyboard instead. (Windows: any key. Linux/macOS: press
                        Enter, then type.)
          text mode  -> press Enter on an empty line to speak a single command
                        without leaving text mode.
 
        For a deliberate switch, say or type "text mode" / "voice mode" — both
        work in either mode, so a misheard STT language can never trap you.
        """
        # Typing or standby: nothing should be holding the mic open.
        if self.input_mode == "text" or self.listen_mode != LISTEN_ACTIVE:
            self._stop_barge_monitor()
        if self.listen_mode == LISTEN_SLEEP:
            return self._listen_while_sleeping()
        if self.listen_mode == LISTEN_PTT and self.input_mode != "text" and self._voice_possible():
            return self._listen_push_to_talk()
        if self.input_mode == "text" or not self._voice_possible():
            label = "You (text): " if self._voice_possible() else "You: "
            typed = self._read_text_input(label)
            if typed == "" and self._voice_possible():
                # Empty Enter = "let me say this one out loud", without
                # disturbing whichever mode you're pinned in.
                return self._listen_voice_input()
            if typed and self.auto_return_to_voice and self._voice_possible():
                # One-shot: this typed turn is done, next one is spoken.
                self._revert_to_voice()
            return typed
 
        pending = self._pending_keyboard_input()
        if pending is not None:
            text, complete = pending
            if not complete:
                try:
                    text += input("")
                except (EOFError, KeyboardInterrupt):
                    pass
            # Already in voice mode, so this was inherently a one-shot — the
            # next turn goes back to the mic with no bookkeeping needed.
            return text.strip()
 
        return self._listen_voice_input()
 
    # --------------------------------------------------------------
    #  PHRASE VARIETY  (greetings, sign-offs, acknowledgements)
    # --------------------------------------------------------------
    def _pick(self, pool, **extra) -> str:
        """Random line from a pool, never the same one twice in a row."""
        last = self._last_pick.get(id(pool))
        choices = [p for p in pool if p != last] or pool
        choice = random.choice(choices)
        self._last_pick[id(pool)] = choice
        return choice.format(u=self.user_name, **extra)

    def _greeting_period(self) -> str:
        hour = self._get_ist_time().hour
        return "morning" if hour < 12 else "afternoon" if hour < 17 else "evening"

    def _sign_off(self) -> str:
        hour = self._get_ist_time().hour
        return self._pick(SIGN_OFFS_NIGHT if (hour >= 21 or hour < 5) else SIGN_OFFS)

    def _warm_up_ollama(self):
        """Load the model into memory in the background while Jupiter is
        greeting you, so the first real question isn't slow."""
        def _go():
            try:
                requests.post(
                    self.ollama_url,
                    json={"model": LLM_MODEL, "think": False, "messages": [{"role": "user", "content": "hi"}],
                          "stream": False, "keep_alive": "30m", "options": {"num_predict": 1}},
                    timeout=(3, 60)
                )
            except Exception:
                pass
        threading.Thread(target=_go, name="jupiter-warmup", daemon=True).start()

    # --------------------------------------------------------------
    #  LISTENING MODES  (always listening / push-to-talk / sleep)
    # --------------------------------------------------------------
    def set_listen_mode(self, mode: str, announce: bool = True):
        """Switch between always-listening and push-to-talk. Remembered
        across restarts. (Sleep has its own method and is never persisted.)"""
        if mode == LISTEN_PTT and not self._voice_possible():
            self.speak(f"Push to talk needs the microphone, {self.user_name}, and voice input isn't available here.")
            return
        self.listen_mode = mode
        self._save_setting("listen_mode", mode)
        if mode == LISTEN_PTT and self.input_mode == "text":
            # Push-to-talk is a voice mode; leave a pinned text mode behind.
            self.input_mode = "voice"
            self._save_setting("input_mode", "voice")
        if announce:
            self.speak(self._pick(PTT_ENTER if mode == LISTEN_PTT else ACTIVE_ENTER))

    def enter_sleep_mode(self):
        """Standby: Jupiter stays running (timers and reminders still fire) but
        ignores everything until a wake phrase."""
        self._mode_before_sleep = self.listen_mode if self.listen_mode != LISTEN_SLEEP else LISTEN_ACTIVE
        self.speak(self._pick(SLEEP_ENTER))
        self.listen_mode = LISTEN_SLEEP

    def wake_from_sleep(self, greet: bool = True):
        self.listen_mode = self._mode_before_sleep or LISTEN_ACTIVE
        if greet:
            self.speak(self._pick(WAKE_FROM_SLEEP))

    def _split_wake(self, text: str, sleeping: bool = False):
        """Look for a wake phrase. Returns (woke, remainder):
          "hey jupiter"                  -> (True, "")
          "hey jupiter what's the time"  -> (True, "what's the time")
          "what's the time, jupiter"     -> (True, "what's the time")
          "Jupiter has how many moons"   -> (False, <unchanged>)  [while active]
        While sleeping, nameless phrases like "wake up" also count, and any
        sentence that starts with the name wakes Jupiter."""
        t = text.strip()
        if WAKE_ONLY_PATTERN.match(t):
            return True, ""
        if sleeping and WAKE_NONAME_PATTERN.match(t):
            return True, ""
        m = WAKE_PREFIX_PATTERN.match(t)
        if m:
            rest = t[m.end():].strip()
            first = rest.split(None, 1)[0].lower().strip(".,!?") if rest else ""
            strong = bool(m.group("lead")) or bool(m.group("punct")) or first in WAKE_COMMAND_VERBS
            if rest and strong:
                return True, rest
            if sleeping:
                return True, t
            return False, text
        tm = WAKE_TRAILING_PATTERN.search(t)
        if tm and t[:tm.start()].strip():
            return True, t[:tm.start()].strip()
        return False, text

    def _listen_while_sleeping(self) -> str:
        """One poll of the standby loop. Returns text ONLY if it contains a
        wake phrase; everything else is dropped on the floor. Uses a short,
        cheap transcription so standby stays light on CPU/GPU."""
        heard = ""
        if self.input_mode == "text" or not self._voice_possible():
            heard = self._read_text_input("(standby) You: ")
        else:
            pending = self._pending_keyboard_input()
            if pending is not None:
                text, complete = pending
                if not complete:
                    try:
                        text += input("")
                    except (EOFError, KeyboardInterrupt):
                        pass
                heard = text.strip()
            else:
                heard = self._listen_voice_input(max_duration=8, quick=True)
        if not heard:
            return ""
        woke, _ = self._split_wake(heard, sleeping=True)
        if woke:
            return heard
        print(f"[standby] ignored: {heard}")
        return ""

    def _poll_ptt_key(self):
        """Non-blocking keyboard check for push-to-talk. Returns None (nothing
        pressed), ("ptt", "") for Enter/Space, or ("text", line) if the user
        started typing a command instead."""
        try:
            if sys.platform == "win32":
                import msvcrt
                if not msvcrt.kbhit():
                    return None
                ch = msvcrt.getwch()
                if ch in ("\r", "\n", " "):
                    return ("ptt", "")
                if ch == "\x03":
                    raise KeyboardInterrupt
                if ch in ("\x00", "\xe0"):      # arrow / function key prefix
                    msvcrt.getwch()
                    return None
                print(f"You (typed): {ch}", end="", flush=True)
                try:
                    rest = input("")
                except (EOFError, KeyboardInterrupt):
                    rest = ""
                return ("text", (ch + rest).strip())
            import select
            if select.select([sys.stdin], [], [], 0)[0]:
                line = sys.stdin.readline().rstrip("\n").strip()
                return ("text", line) if line else ("ptt", "")
            return None
        except KeyboardInterrupt:
            raise
        except Exception:
            return None

    def _listen_push_to_talk(self) -> str:
        """Wait for Enter/Space, then record ONE utterance. Typing a command
        and pressing Enter also works. The mic stays closed until you press a
        key, and reminders/timers are still announced while waiting."""
        print("[Push to talk] Press Enter or Space, then speak (or type a command).", flush=True)
        while self.is_running:
            self.drain_events()
            key = self._poll_ptt_key()
            if key is None:
                time.sleep(0.05)
                continue
            kind, text = key
            if kind == "text":
                return text
            return self._listen_voice_input()
        return ""

    def _revert_to_voice(self):
        """Silently return to voice input after a one-shot typed command. No
        announcement — the whole point is that switching costs you nothing."""
        self.input_mode = "voice"
        self._save_setting("input_mode", "voice")
 
    def _listen_voice_input(self, max_duration=None, quick: bool = False, keep_short: bool = False):
        """Record from the microphone until you stop speaking, then transcribe
        straight from memory (nothing is written to disk). Short commands finish
        fast, longer sentences aren't cut off at a mid-sentence pause. Falls back
        to text input if audio isn't available."""
        if not audio_input_available:
            return self._read_text_input("You: ")

        if not (whisper_available and hasattr(self, 'whisper_model')):
            return self._read_text_input("You (Whisper unavailable): ")

        # The "stop" listener owns the mic while Jupiter is talking; hand it
        # over before opening our own stream.
        self._stop_barge_monitor()

        chunk_duration = 0.1  # seconds analyzed per iteration
        chunk_samples = int(self.sample_rate * chunk_duration)
        speech_chunks_needed = max(1, int(self.min_speech_duration / chunk_duration))
        max_chunks = int((max_duration or self.max_listen_duration) / chunk_duration)

        chunks = []
        silence_run = 0
        speech_run = 0
        speech_started = False
        speech_start_idx = 0
        last_speech_idx = 0
        stream = None

        def _note(is_speech, idx):
            nonlocal silence_run, speech_run, speech_started, speech_start_idx, last_speech_idx
            if is_speech:
                speech_run += 1
                silence_run = 0
                last_speech_idx = idx
                if speech_run >= speech_chunks_needed and not speech_started:
                    speech_started = True
                    speech_start_idx = idx - speech_run + 1
            else:
                silence_run += 1
                speech_run = 0

        try:
            with _AUDIO_OPEN_LOCK:
                stream = sd.InputStream(samplerate=self.sample_rate, channels=1, dtype='float32')
                stream.start()

            # Briefly sample ambient noise and raise the effective threshold
            # above it if the room/mic is noisier than the fixed default
            # assumes. The audio is KEPT (not thrown away), and the quietest
            # chunk is used as the floor, so speech that starts inside this
            # window doesn't inflate it.
            calibration_chunks = max(1, int(0.4 / chunk_duration))
            ambient_levels = []
            for _ in range(calibration_chunks):
                data, _unused = stream.read(chunk_samples)
                chunks.append(data.copy())
                ambient_levels.append(float(np.sqrt(np.mean(data.astype(np.float64) ** 2))))
            ambient_rms = min(ambient_levels)
            effective_threshold = max(self.silence_threshold, ambient_rms * 3)
            heard_early = max(ambient_levels) > effective_threshold

            if not quick:
                print("Listening... (speak now)", flush=True)

            # Speech that began INSIDE the calibration window counts too - a
            # one-word command said right after the mic opens (e.g. straight
            # after "stop") used to be missed entirely.
            for i, level in enumerate(ambient_levels):
                _note(self._is_speech_chunk(chunks[:i + 1], level, effective_threshold, ambient_rms), i)

            for _ in range(max_chunks):
                data, _unused = stream.read(chunk_samples)
                chunks.append(data.copy())
                idx = len(chunks) - 1
                rms = float(np.sqrt(np.mean(data.astype(np.float64) ** 2)))
                _note(self._is_speech_chunk(chunks, rms, effective_threshold, ambient_rms), idx)

                # Stop once we've heard real speech followed by enough silence.
                # A longer sentence gets a longer grace period before we decide
                # you're done.
                if speech_started:
                    spoken = (last_speech_idx - speech_start_idx + 1) * chunk_duration
                    limit = self.silence_limit_long if spoken > 2.5 else self.silence_limit
                    if silence_run >= max(1, int(round(limit / chunk_duration))):
                        break

            stream.stop()
            stream.close()
            stream = None

            if not speech_started:
                if not quick:
                    print("No speech detected.")
                return ""

            # Trim to the speech plus a little padding. Whisper pads every clip to
            # 30 s anyway, so this isn't about speed - it's that long stretches of
            # silence are exactly what it hallucinates "Thank you." out of.
            first = 0 if heard_early else max(0, speech_start_idx - 4)
            last = min(len(chunks), last_speech_idx + 1 + 3)
            audio = np.concatenate(chunks[first:last], axis=0)
            if self.audio_cleanup:
                audio = self._clean_audio(audio)

            text = self.transcribe(audio, quick=quick, keep_short=keep_short)

            if text:
                print(f"You said: {text}")
                return text
            if not quick:
                print("No speech detected.")
            return ""

        except Exception as e:
            print(f"[Audio Error] {e}")
            return self._read_text_input("You (text fallback): ")

        finally:
            if stream is not None:
                try:
                    stream.stop()
                    stream.close()
                except Exception:
                    pass

    def _is_speech_chunk(self, chunks, rms, effective_threshold, ambient_rms) -> bool:
        """Is the audio that just arrived actual speech? Uses Silero VAD on the
        last ~0.6s and only counts it if speech is still going at the very end
        of that window, so a sentence that just finished isn't counted as
        speech for another half second. Falls back to the old loudness check
        if VAD isn't available or errors."""
        if not vad_available or getattr(self, "_vad_broken", False):
            return rms > effective_threshold
        # Cheap gate: clearly-quiet chunks are never speech, no model call.
        if rms < max(0.004, ambient_rms * 1.5):
            return False
        try:
            window = np.concatenate(chunks[-6:], axis=0).reshape(-1).astype(np.float32)
            opts = _FWVadOptions(
                threshold=self.vad_threshold,
                min_speech_duration_ms=100,
                min_silence_duration_ms=100,
                speech_pad_ms=0,
            )
            ts = _fw_speech_ts(window, opts)
            if not ts:
                return False
            return ts[-1]["end"] >= len(window) - int(0.12 * self.sample_rate)
        except Exception as e:
            print(f"[VAD Error] {e} - using loudness-based detection instead")
            self._vad_broken = True
            return rms > effective_threshold

    def _clean_audio(self, audio):
        """Mild clean-up before Whisper: cut rumble below ~80 Hz (fan, desk
        thumps) and lift a quiet recording to a healthy level. Deliberately
        NOT a heavy denoiser - Whisper is trained on noisy audio and
        aggressive filtering usually makes it worse."""
        try:
            x = audio.reshape(-1).astype(np.float32)
            if len(x) < 1600:
                return audio
            spec = np.fft.rfft(x)
            freqs = np.fft.rfftfreq(len(x), 1.0 / self.sample_rate)
            spec[freqs < 80] = 0
            x = np.fft.irfft(spec, n=len(x)).astype(np.float32)
            peak = float(np.max(np.abs(x)))
            if 0.003 < peak < 0.5:
                x *= min(0.7 / peak, 8.0)
            return np.clip(x, -1.0, 1.0).reshape(-1, 1)
        except Exception:
            return audio

    def store_conversation(self, role: str, message: str):
        """Persist a single utterance in the current conversation."""
        # Guarded by _db_lock: the scheduler thread also touches self.conn
        # (reminders), and sqlite3 connections aren't safe to use from two
        # threads at once without serialising access like this.
        with self._db_lock:
            self.conn.execute(
                """
                INSERT INTO conversations (conv_id, timestamp, role, message)
                VALUES (?, ?, ?, ?)
                """,
                (self.current_conv_id, self._get_ist_time().isoformat(), role, message)
            )
            self.conn.commit()
 
    def run(self):
        """Main loop"""
        print("=" * 50)
        print("JUPITER IS ONLINE")
        print("=" * 50)
 
        while self.is_running:
            try:
                # Speak anything the scheduler queued (due reminders, finished
                # timers). Done here, on the main thread, so TTS never overlaps
                # with recording or with another utterance.
                # A new turn: speech is allowed again after a "stop".
                self._interrupted.clear()
                self.drain_events()
 
                user_input = self.listen_for_command()
                if not user_input:
                    continue

                # Wake phrases ("hey jupiter", "sup jupiter", "jupiter you there?"):
                # on standby they wake Jupiter; otherwise a bare one just gets an
                # acknowledgement, and a leading one is stripped off the command.
                sleeping = self.listen_mode == LISTEN_SLEEP
                woke, remainder = self._split_wake(user_input, sleeping=sleeping)
                if sleeping:
                    if not woke:
                        continue
                    self.wake_from_sleep(greet=not remainder)
                    if not remainder:
                        continue
                    user_input = remainder
                elif woke:
                    if not remainder:
                        self.speak(self._pick(WAKE_ACKS))
                        continue
                    user_input = remainder
 
                # "stop" with nothing playing has nothing to do (and no longer
                # shuts Jupiter down - say quit / exit / goodbye for that).
                if INTERRUPT_PATTERN.match(user_input.strip()):
                    print("[stop] nothing is playing.")
                    continue
                self.store_conversation("user", user_input)
                self._last_response = None
                action_handled = self.handle_action(self._normalise_command(user_input))
 
                # Only learn from commands that actually WORKED. A misheard
                # command that fell through to the LLM is exactly the garbage
                # we don't want permanently biasing Whisper's decoding.
                if action_handled and not getattr(self, "_skip_vocab", False):
                    self.maybe_learn_vocabulary(user_input)
 
                if action_handled:
                    # Direct-action commands (weather, timers, "open X", ...)
                    # never went through store_conversation before, so
                    # conversation history/summaries silently skipped them.
                    # speak() always records its last line in
                    # self._last_response; for handlers that speak more than
                    # once (e.g. list_timers) this only captures the final
                    # line, which is a reasonable summary rather than a full
                    # replay of everything spoken.
                    if self._last_response:
                        self.store_conversation("jupiter", self._last_response)
                else:
                    # Streaming speaks each sentence as it arrives, so there's
                    # no silence while the model finishes. It falls back to the
                    # blocking path by itself if streaming fails.
                    response = self.think_stream(user_input)
                    self.store_conversation("jupiter", response)
 
            except KeyboardInterrupt:
                self.interrupt_speech()
                self._interrupted.clear()
                self.speak(self._sign_off())
                self.is_running = False
                break
            except Exception as e:
                print(f"Error: {e}")
                continue
 
        self.shutdown()
 
    def shutdown(self):
        """Stop the scheduler, flush the DB and clean up stray TTS files.
        Safe to call more than once."""
        try:
            self.interrupt_speech()
            self._stop_barge_monitor()
            self._close_out_stream()
        except Exception as e:
            print(f"[Shutdown Error] {e}")
        try:
            if getattr(self, "_scheduler_stop", None):
                self._scheduler_stop.set()
            if getattr(self, "_scheduler", None) and self._scheduler.is_alive():
                self._scheduler.join(timeout=2.0)
        except Exception as e:
            print(f"[Shutdown Error] {e}")
        # Remove any TTS wavs this process left behind — only files matching
        # our own pid-prefixed naming, inside our own data folder.
        try:
            for path in glob.glob(os.path.join(self.data_dir, f"tts_{os.getpid()}_*.wav")):
                try:
                    os.remove(path)
                except OSError:
                    pass
        except Exception:
            pass
        try:
            self.conn.commit()
            self.conn.close()
        except Exception:
            pass
 
 
if __name__ == "__main__":
    jupiter = Jupiter()
    jupiter.run()