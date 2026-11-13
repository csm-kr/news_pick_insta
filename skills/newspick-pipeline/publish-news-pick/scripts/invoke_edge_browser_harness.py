#!/usr/bin/env python3
"""Feed one browser script as exact bytes to the fixed News Pick Edge connection."""

from __future__ import annotations

import argparse
from pathlib import Path

import edge_browser


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("script", type=Path)
    parser.add_argument("--timeout", type=float)
    args = parser.parse_args()
    completed = edge_browser.run_script(args.script, timeout=args.timeout)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())

