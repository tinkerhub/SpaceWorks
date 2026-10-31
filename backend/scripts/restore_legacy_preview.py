#!/usr/bin/env python3
"""Fixed same-host identity check on the controller's disposable preview database."""

import os
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit, urlunsplit

import psycopg2

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from apps.backup.full_restore_identity import read_private_control, verify_legacy_dump_identity


def main():
    if os.geteuid() != 0 or len(sys.argv) != 2 or not re.fullmatch(r"spaceworks_restore_[0-9a-f]{32}", sys.argv[1]):
        raise RuntimeError("Fixed historical preview refused.")
    parsed = urlsplit(os.environ["DATABASE_URL"])
    url = urlunsplit((parsed.scheme, parsed.netloc, "/" + sys.argv[1], parsed.query, ""))
    control = read_private_control(sys.stdin)
    with psycopg2.connect(url) as database:
        verify_legacy_dump_identity(database, control["full_target_identity"])
    print("legacy-preview-identity-ok")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        raise SystemExit("Fixed historical preview identity refused.") from None
