from ..common import *


class WebService:
    def translate_text(self, text, target_lang="es"):
        """Translate using Argos Translate (primary) or AI fallback"""
        lang_map = {
            "spanish": "es", "french": "fr", "german": "de",
            "chinese": "zh", "japanese": "ja", "korean": "ko",
            "russian": "ru", "italian": "it", "portuguese": "pt"
        }
        target = lang_map.get(target_lang.lower(), target_lang)

        # Load Argos only when translation is requested. This keeps the normal
        # JUPITER startup independent of Argos/SpaCy native extensions.
        try:
            import argostranslate.translate as argos_translate
            return argos_translate.translate(text, "en", target)
        except Exception as e:
            print(f"[Argos Error] {e}")

        # Fallback: Use AI brain
        prompt = f"Translate to {target_lang}: {text}"
        return self.think(prompt)

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
