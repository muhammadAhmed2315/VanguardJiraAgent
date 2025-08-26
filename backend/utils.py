import re
import logging
from dateutil import parser
from datetime import datetime, timezone


def replace_iso8601_with_relative(text: str) -> str:
    """
    Given an string that contains one or more ISO 8601 timestamps, this function
    replaces all of those timestamps with their relative time difference compared to
    the current UTC time, and then returns the new string.

    Args:
        timestamp: A string that may contain one or more ISO 8601 timestamps.

    Returns:
        str: The input string with all ISO 8601 timestamps replaced by their relative
            time difference from now.
    """
    iso_pattern = (
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?"
    )

    def convert(match):
        ts = match.group()
        try:
            dt = parser.isoparse(ts)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)

            now = datetime.now(timezone.utc)
            seconds = int((now - dt).total_seconds())

            if seconds < 60:
                return f"{seconds} seconds ago"
            elif seconds < 3600:
                return f"{seconds // 60} minutes ago"
            elif seconds < 86400:
                return f"{seconds // 3600} hours ago"
            else:
                return f"{seconds // 86400} days ago"
        except Exception:
            logging.error(f"Timestamp {text} could not be parsed")
            return "Invalid timestamp"

    return re.sub(iso_pattern, convert, text)
