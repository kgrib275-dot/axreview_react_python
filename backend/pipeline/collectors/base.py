from __future__ import annotations

import time
from datetime import datetime, timezone


def parse_feed_entry_published(entry) -> datetime | None:
    struct = getattr(entry, "published_parsed", None) or getattr(entry, "updated_parsed", None)
    if struct is None:
        return None
    return datetime.fromtimestamp(time.mktime(struct), tz=timezone.utc)
