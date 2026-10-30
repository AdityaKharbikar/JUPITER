from ..common import *


class SystemService:
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
