from ..common import *


class PhraseMixin:
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
