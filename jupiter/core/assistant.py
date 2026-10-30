import time
from ..common import *
from .constants import ConstantsMixin
from .settings import SettingsMixin
from .vocabulary import VocabularyMixin
from .time_utils import TimeMixin
from .phrases import PhraseMixin
from .conversation import ConversationMixin
from .legacy_actions import LegacyActionsMixin
from .router import HybridRouter
from ..services.calculator import CalculatorService
from ..services.web import WebService
from ..services.media import MediaService
from ..services.navigation import NavigationService
from ..services.weather import WeatherService
from ..services.system import SystemService
from ..services.scheduler import SchedulerService
from ..services.timers import TimerService
from ..services.reminders import ReminderService
from ..services.notes_clipboard import NotesClipboardService
from ..services.documents import DocumentService
from ..services.usage import UsageService
from ..services.productivity import ProductivityService
from ..services.watchdog import Watchdog
from ..audio.speech import SpeechMixin
from ..audio.stt import STTMixin
from ..audio.barge_in import BargeInMixin
from ..audio.modes import AudioModesMixin
from ..models.llm import LLMMixin
from ..models.model_router import ModelRouter

class Jupiter(
    ConstantsMixin,
    SettingsMixin, VocabularyMixin, TimeMixin, PhraseMixin, ConversationMixin,
    CalculatorService, WebService, MediaService, NavigationService, WeatherService,
    SystemService, SchedulerService, TimerService, ReminderService, NotesClipboardService,
    DocumentService, UsageService, ProductivityService, SpeechMixin, STTMixin, BargeInMixin, AudioModesMixin,
    LLMMixin, LegacyActionsMixin
):
    def __init__(self):
        self.project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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
        self.silence_limit = 0.45        # quiet after a SHORT command that ends the recording (seconds)
        self.silence_limit_long = 0.8   # quiet that ends a longer sentence (people pause mid-sentence more)
        self.vad_threshold = 0.42        # Silero speech probability needed (0.4 = more sensitive, 0.6 = stricter)
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
        # Piper length_scale controls speech duration. Lower = faster speech.
        # Default 0.70 is a more natural/slower setting than the previous 0.55 while
        # remaining understandable. Override in PowerShell with
        # $env:JUPITER_TTS_SPEED = "0.75" (slower) or "0.55" (faster).
        try:
            self.tts_length_scale = max(0.45, min(1.0, float(os.environ.get("JUPITER_TTS_SPEED", "0.70"))))
        except ValueError:
            self.tts_length_scale = 0.70
        self.min_speech_duration = 0.22  # seconds of sound needed to count as real speech
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
        self._previous_response = ""
        self._vocab_version = 0
        self._vocab_hint_cache = None
        self._geo_cache = {}
        # One keep-alive HTTP session for Ollama / Nominatim: avoids a new TCP
        # handshake on every request.
        self.http = requests.Session()
        # Skill router: deterministic skills run first; legacy dispatcher remains the fallback during migration.
        self.router = HybridRouter(self)
        self.model_router = ModelRouter(self)
        self.last_model = self.model_router.GENERAL_MODEL
        self.last_llm_latency = 0.0
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
        self.current_mode = "normal"
        self._last_full_text = None
        self._last_code = None
        self.watchdog = Watchdog(self)      # proactive alerts (RAM / CPU / battery)
        self.watchdog.start()
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
        try:                                # 3D Explainer: pre-build the curated models in the background (instant first request)
            from ..skills.explainer import ExplainerSkill
            ExplainerSkill.service(self).start_pregen()
        except Exception as exc:
            print(f"[Explainer] pre-generation skipped: {exc}")

    def dispatch_command(self, command: str) -> bool:
        """New command entry point. Skills get first chance; legacy handler is the fallback during migration."""
        # Each command starts clean. Legacy handlers can suppress vocabulary
        # prompts, so that state must never leak into the next turn.
        self._skip_vocab = False
        now = time.time()
        if now - getattr(self, "_last_turn_ts", 0) > 900:      # new work session (15 min gap)
            self._streak_start = now
        self._last_turn_ts = now
        self._pending_router_command = command
        skill, args = self.router.route(command)
        if skill is not None:
            try:
                result = skill.execute(args, self)
                return bool(result.handled) if result is not None else True
            except Exception as exc:
                print(f"[Skill Error] {skill.name}: {exc}; falling back to legacy handler")
        return self.handle_action(command)

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
                self._previous_response = getattr(self, "_last_response", "")
                self._last_response = None
                self._pending_router_command = self._normalise_command(user_input)
                action_handled = self.dispatch_command(self._pending_router_command)

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
