"""HackerOne public program directory adapter.

Not implemented yet — see TODO.md v1, "HackerOne public program directory
adapter." HackerOne exposes a public JSON:API directory of programs that
accept public submissions; this is the first adapter to build because it
needs no API token for that subset.
"""

from __future__ import annotations

from ..models import Program
from . import register

PLATFORM = "hackerone"


def fetch_programs() -> list[Program]:
    raise NotImplementedError(
        "HackerOne adapter not implemented yet — see TODO.md v1."
    )


register(PLATFORM, fetch_programs)
