from ..common import *


class TimeMixin:
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
