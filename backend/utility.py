import re
from dateutil import parser
from datetime import datetime, timezone


def replace_iso8601_with_relative(text: str) -> str:
    # Regex for ISO 8601 timestamps
    iso_pattern = (
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?"
    )

    def convert(match):
        ts = match.group(0)
        dt = parser.isoparse(ts)
        now = datetime.now(timezone.utc)
        delta = now - dt
        seconds = int(delta.total_seconds())

        if seconds < 60:
            return f"{seconds} seconds ago"
        elif seconds < 3600:
            return f"{seconds // 60} minutes ago"
        elif seconds < 86400:
            return f"{seconds // 3600} hours ago"
        else:
            return f"{seconds // 86400} days ago"

    return re.sub(iso_pattern, convert, text)
