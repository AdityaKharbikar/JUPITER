from ..common import *


class NavigationService:
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
