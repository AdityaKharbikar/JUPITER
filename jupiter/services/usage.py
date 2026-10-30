from ..common import *


class UsageService:
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
