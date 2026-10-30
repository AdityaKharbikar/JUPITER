from ..common import *


class WeatherService:
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
