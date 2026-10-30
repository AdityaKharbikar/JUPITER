from pathlib import Path
from jupiter.skills.registry import SkillRegistry, default_skills
from jupiter.services.web import WebService
from jupiter.services.documents import DocumentService


def route(text):
    skill, args = SkillRegistry(default_skills()).route(text)
    return (skill.name if skill else None, args)


def test_general_questions_do_not_route_to_calculator():
    assert route("what is my battery level")[0] == "system"
    assert route("what is my network name")[0] == "system"
    assert route("what is the weather in Pune")[0] == "weather"
    assert route("what is the difference between a process and a thread")[0] is None
    assert route("what is my project called")[0] is None
    assert route("what is today's date")[0] == "information"


def test_conversion_routes_are_valid():
    assert route("convert 10 km to miles")[0] == "conversion"
    assert route("convert 100 cm to meters")[0] == "conversion"
    assert route("convert 100 c to f")[0] == "conversion"


def test_conversion_helpers_have_correct_bound_method_signatures():
    assert WebService._fmt_number(2.5400) == "2.54"
    assert WebService._convert_temperature(100, "c", "f") == 212


def test_document_helpers_have_correct_bound_method_signatures():
    chunks = DocumentService._chunk_text("This is a small document. " * 5)
    assert chunks
    assert all(len(chunk) > 40 for chunk in chunks)


def test_greeting_skill_imports_reply_tables():
    skill, args = SkillRegistry(default_skills()).route("hello")
    assert skill.name == "greeting"
    assert args["op"] == "greet"


def test_file_and_app_commands_route_to_media():
    assert route(r"open file C:\JUPITER\test_docs\test.txt")[0] == "media"
    assert route("open Chrome")[0] == "media"
    assert route("open VS Code")[0] == "media"


def test_skills_do_not_speak_none_after_services():
    from jupiter.skills.system import SystemSkill
    from jupiter.skills.conversion import ConversionSkill

    class FakeAssistant:
        user_name = "sir"
        _last_response = "ok"
        calls = []

        def get_battery_status(self):
            self.calls.append("battery")
            return None

        def get_network_info(self):
            self.calls.append("network")
            return None

        def get_system_stats(self):
            self.calls.append("stats")
            return None

        def set_volume(self, direction=None, level=None):
            self.calls.append(("volume", direction, level))
            return None

        def convert_units(self, *args):
            self.calls.append(("convert", args))
            return None

    a = FakeAssistant()
    SystemSkill().execute({"op": "battery"}, a)
    SystemSkill().execute({"op": "network"}, a)
    ConversionSkill().execute({"amount": "10", "src": "km", "dst": "miles"}, a)
    assert a.calls == ["battery", "network", ("convert", ("10", "km", "miles"))]


def test_explicit_file_open_routes_before_generic_app():
    skill, args = SkillRegistry(default_skills()).route(r"open file C:\JUPITER\test_docs\test.txt")
    assert skill.name == "media"
    assert args["op"] == "path"
    assert args["path"].endswith(r"test_docs\test.txt")


def test_windows_app_resolution_code_contains_registry_and_start_menu_fallbacks():
    from pathlib import Path as _Path
    source = _Path("jupiter/services/media.py").read_text()
    assert "winreg" in source
    assert "App Paths" in source
    assert "Start Menu" in source
    assert "StartMenuInternet" in source
    assert "DisplayName" in source


def test_tts_speed_defaults_faster_than_previous_value():
    from pathlib import Path as _Path
    source = _Path("jupiter/audio/speech.py").read_text()
    assert 'getattr(self, "tts_length_scale", 0.70)' in source


def test_chrome_and_vscode_are_resolved_even_when_aliases_exist_in_app_commands():
    source = __import__("pathlib").Path("jupiter/services/media.py").read_text()
    assert "key in {" in source
    assert '"chrome", "google chrome", "vs code", "vscode", "visual studio code"' in source
    assert 'cmd = APP_COMMANDS.get(key)' in source
    assert '_resolve_windows_app(key, fallback_exe)' in source
    assert 'cmd.exe", "/d", "/c", "start"' in source


def test_file_path_regex_handles_windows_paths():
    import re
    from jupiter.common import OPEN_FILE_PATTERN
    m = OPEN_FILE_PATTERN.match(r"open file C:\JUPITER\test_docs\test.txt")
    assert m
    assert m.group(1) == r"C:\JUPITER\test_docs\test.txt"



def test_media_commands_skip_vocabulary_learning_for_paths_and_apps():
    source = Path("jupiter/skills/media.py").read_text()
    assert "assistant._skip_vocab = True" in source


def test_dispatch_resets_skip_vocab_each_turn():
    source = Path("jupiter/core/assistant.py").read_text()
    assert 'self._skip_vocab = False' in source
    assert 'self._pending_router_command = command' in source



def test_speak_defensively_ignores_none_responses():
    source = Path("jupiter/audio/speech.py").read_text()
    assert 'if text is None:' in source
    assert '        return\n        text = str(text)' in source



def test_chrome_registry_lookup_is_scoped_to_chrome_requests():
    source = Path("jupiter/services/media.py").read_text()
    marker = 'if "chrome" in key:'
    browser_marker = 'browser_keys = ['
    assert marker in source
    assert source.index(marker) < source.index(browser_marker)
