#!/usr/bin/env python3
"""Bug Spray — entry point.

    python main.py --selftest   check config/store/adapters wire up, no network
    python main.py scan         fetch enabled platforms, store, print what changed
"""

import sys

from bug_spray.cli import main

if __name__ == "__main__":
    sys.exit(main())
