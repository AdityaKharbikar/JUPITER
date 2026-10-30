from ..common import *


class MediaService:
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

    def _resolve_windows_app(self, key: str, fallback_exe: str):
        """Resolve a known Windows GUI app without relying on PATH alone.

        Some Chrome/VS Code installs are per-user and are absent from PATH.
        We therefore check: PATH, Windows App Paths registry keys, common
        per-machine/per-user install folders, and finally a fixed Windows
        ``start`` alias for these two known apps. No user text is inserted into
        the shell command.
        """
        if sys.platform != "win32":
            return None

        found = shutil.which(fallback_exe)
        if found:
            return found

        registry_candidates = []
        try:
            import winreg
            subkeys = [
                r"Software\Microsoft\Windows\CurrentVersion\App Paths" + "\\" + fallback_exe,
                r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths" + "\\" + fallback_exe,
            ]
            for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
                for subkey in subkeys:
                    try:
                        with winreg.OpenKey(hive, subkey) as hkey:
                            value, _ = winreg.QueryValueEx(hkey, None)
                            if value:
                                registry_candidates.append(os.path.expandvars(value.strip('"')))
                    except (FileNotFoundError, OSError):
                        pass
        except Exception as e:
            print(f"[App Registry Lookup] {e}")

        # Chrome can be registered as the system browser without an App Paths
        # key. Only perform this lookup for a Chrome request. The previous
        # version ran this block for *every* app, so "open VS Code" could
        # accidentally return Chrome's registered executable.
        if "chrome" in key:
            try:
                browser_keys = [
                    r"Software\Clients\StartMenuInternet\Google Chrome\shell\open\command",
                    r"Software\WOW6432Node\Clients\StartMenuInternet\Google Chrome\shell\open\command",
                ]
                for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
                    for subkey in browser_keys:
                        try:
                            with winreg.OpenKey(hive, subkey) as hkey:
                                command, _ = winreg.QueryValueEx(hkey, None)
                                match = re.match(r'\s*"([^"]+\.exe)"', str(command), re.IGNORECASE)
                                if match:
                                    candidate = os.path.expandvars(match.group(1))
                                    if os.path.isfile(candidate):
                                        return candidate
                        except (FileNotFoundError, OSError):
                            pass
            except Exception as e:
                print(f"[Chrome Registry Lookup] {e}")

        # VS Code may use a custom install directory. Its uninstall entry stores
        # that directory even when Code.exe is not on PATH.
        try:
            uninstall_roots = [
                r"Software\Microsoft\Windows\CurrentVersion\Uninstall",
                r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
            ]
            for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
                for root_key in uninstall_roots:
                    try:
                        with winreg.OpenKey(hive, root_key) as root:
                            for i in range(winreg.QueryInfoKey(root)[0]):
                                try:
                                    name = winreg.EnumKey(root, i)
                                    with winreg.OpenKey(root, name) as item:
                                        display, _ = winreg.QueryValueEx(item, "DisplayName")
                                        if "visual studio code" not in str(display).lower():
                                            continue
                                        install, _ = winreg.QueryValueEx(item, "InstallLocation")
                                        candidate = os.path.join(os.path.expandvars(str(install)), "Code.exe")
                                        if os.path.isfile(candidate):
                                            return candidate
                                except (FileNotFoundError, OSError):
                                    pass
                    except (FileNotFoundError, OSError):
                        pass
        except Exception as e:
            print(f"[VS Code Registry Lookup] {e}")

        for candidate in registry_candidates:
            if os.path.isfile(candidate):
                return candidate

        local = os.environ.get("LOCALAPPDATA", "")
        program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
        program_files_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        common = {
            "chrome": [
                os.path.join(local, "Google", "Chrome", "Application", "chrome.exe"),
                os.path.join(program_files, "Google", "Chrome", "Application", "chrome.exe"),
                os.path.join(program_files_x86, "Google", "Chrome", "Application", "chrome.exe"),
            ],
            "google chrome": [
                os.path.join(local, "Google", "Chrome", "Application", "chrome.exe"),
                os.path.join(program_files, "Google", "Chrome", "Application", "chrome.exe"),
                os.path.join(program_files_x86, "Google", "Chrome", "Application", "chrome.exe"),
            ],
            "vs code": [
                os.path.join(local, "Programs", "Microsoft VS Code", "Code.exe"),
                os.path.join(program_files, "Microsoft VS Code", "Code.exe"),
                os.path.join(program_files_x86, "Microsoft VS Code", "Code.exe"),
            ],
            "vscode": [
                os.path.join(local, "Programs", "Microsoft VS Code", "Code.exe"),
                os.path.join(program_files, "Microsoft VS Code", "Code.exe"),
                os.path.join(program_files_x86, "Microsoft VS Code", "Code.exe"),
            ],
            "visual studio code": [
                os.path.join(local, "Programs", "Microsoft VS Code", "Code.exe"),
                os.path.join(program_files, "Microsoft VS Code", "Code.exe"),
                os.path.join(program_files_x86, "Microsoft VS Code", "Code.exe"),
            ],
        }
        for candidate in common.get(key, []):
            if os.path.isfile(candidate):
                return candidate

        # Start-menu shortcuts are useful for Microsoft Store/managed installs.
        start_menu = [
            os.path.join(os.environ.get("PROGRAMDATA", r"C:\ProgramData"), "Microsoft", "Windows", "Start Menu", "Programs"),
            os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Start Menu", "Programs"),
            os.path.join(local, "Microsoft", "Windows", "Start Menu", "Programs"),
        ]
        shortcut_names = {
            "chrome": ["Google Chrome.lnk", "Chrome.lnk"],
            "google chrome": ["Google Chrome.lnk", "Chrome.lnk"],
            "vs code": ["Visual Studio Code.lnk", "VS Code.lnk"],
            "vscode": ["Visual Studio Code.lnk", "VS Code.lnk"],
            "visual studio code": ["Visual Studio Code.lnk", "VS Code.lnk"],
        }
        for base in start_menu:
            if not os.path.isdir(base):
                continue
            names = shortcut_names.get(key, [])
            for root, _dirs, files in os.walk(base):
                for name in files:
                    if name.lower() in {n.lower() for n in names}:
                        return os.path.join(root, name)

        # Last resort for these fixed aliases only. Windows' START command can
        # resolve registered/per-user applications even when the executable is
        # not present in PATH and no App Paths key is available. The alias is a
        # hardcoded value; the user's app_name is never inserted into this command.
        start_alias = {
            "chrome": "chrome.exe",
            "google chrome": "chrome.exe",
            "vs code": "code.exe",
            "vscode": "code.exe",
            "visual studio code": "code.exe",
        }.get(key)
        if start_alias:
            return ("start", start_alias)
        return None

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
        raw = app_name.strip()
        key = raw.lower()

        # Explicit file/folder paths are handled separately. This keeps
        # "open file C:\\..." from being mistaken for an application name.
        path_match = re.match(r"^(?:file|folder)\s+(.+)$", raw, re.IGNORECASE)
        if path_match:
            target = os.path.expandvars(os.path.expanduser(path_match.group(1).strip().strip('"')))
            if os.path.exists(target):
                try:
                    if sys.platform == "win32":
                        if os.path.isdir(target):
                            subprocess.Popen(["explorer", target])
                        else:
                            os.startfile(target)
                    elif sys.platform == "darwin":
                        subprocess.Popen(["open", target])
                    else:
                        subprocess.Popen(["xdg-open", target])
                    self.speak(f"Opening {os.path.basename(target) or target}, sir.")
                except Exception as e:
                    print(f"[Open Path Error] {e}")
                    self.speak(f"I couldn't open {target}, sir.")
            else:
                self.speak(f"I couldn't find {target}, sir.")
            return

        cmd = APP_COMMANDS.get(key)

        # Chrome and VS Code are special because their Windows installers often
        # do not put the executable on PATH. Even though APP_COMMANDS contains
        # an alias for them, resolve the real installation first.
        if sys.platform == "win32" and key in {
            "chrome", "google chrome", "vs code", "vscode", "visual studio code"
        }:
            fallback_exe = "chrome.exe" if "chrome" in key else "Code.exe"
            resolved = self._resolve_windows_app(key, fallback_exe)
            if resolved:
                cmd = resolved

        if not cmd and key in DANGEROUS_APP_NAMES:
            self.speak(f"I won't open {app_name}, sir — that's a system utility I keep off-limits by voice.")
            return

        try:
            if cmd:
                if isinstance(cmd, tuple) and cmd[0] == "start":
                    # Fully fixed alias chosen above; no spoken/typed text is
                    # passed to cmd.exe.
                    subprocess.run(["cmd.exe", "/d", "/c", "start", "", cmd[1]], check=False)
                elif isinstance(cmd, str) and cmd.endswith(".lnk"):
                    os.startfile(cmd)
                elif isinstance(cmd, str) and cmd.startswith("start "):
                    # Fixed string from our own dict — never user input — safe with shell=True.
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
