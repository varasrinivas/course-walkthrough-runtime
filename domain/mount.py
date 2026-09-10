# -*- coding: utf-8 -*-
"""mount — put the one placeholder the domain runtime needs into a course page.

That is the whole integration. The runtime builds its own panel, popover and
opener, and hydrates itself off a MutationObserver, so unlike the walkthrough
there is no per-module mount point to place and no player code to change.

The placeholder goes immediately before </body>, and after the walkthrough's
WT:END when that is present — the two generated regions must never nest.

Idempotent: a page that already carries the placeholder, or a previously built
block, is left alone.

Usage:
    python mount.py --html "output/*.html"
    python mount.py --html course/index.html
"""
from __future__ import annotations

import argparse
import glob as globmod
import re
import sys
from pathlib import Path

PLACEHOLDER = "<!-- DG:BUNDLE -->"
START, END = "<!-- DG:START -->", "<!-- DG:END -->"
WT_END = "<!-- WT:END -->"

EXCLUDE = ("scripts/dist", "node_modules", ".venv", "archive", "dist/")


def mount(path: Path) -> str:
    raw = path.read_text(encoding="utf-8", errors="replace")
    if PLACEHOLDER in raw:
        return "already mounted"
    if START in raw and END in raw:
        return "already built"

    m = re.search(r"</body\s*>", raw, re.I)
    if not m:
        return "SKIPPED — no </body>"

    at = m.start()
    # Keep our region out of the walkthrough's, and adjacent to it for
    # readability when both are present.
    wt = raw.rfind(WT_END)
    if wt != -1 and wt < at:
        at = wt + len(WT_END)
        block = "\n" + PLACEHOLDER
    else:
        block = PLACEHOLDER + "\n"

    nl = "\r\n" if "\r\n" in raw else "\n"
    out = raw[:at] + block.replace("\n", nl) + raw[at:]
    path.write_text(out, encoding="utf-8", newline="")
    return "mounted"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--html", action="append", required=True, help="glob(s), repeatable")
    args = ap.parse_args()

    files = []
    for pattern in args.html:
        files += [Path(h) for h in sorted(globmod.glob(pattern, recursive=True))
                  if Path(h).is_file() and not any(x in Path(h).as_posix() for x in EXCLUDE)]
    if not files:
        print(f"nothing matched {args.html}")
        return 1

    counts: dict[str, int] = {}
    for path in files:
        result = mount(path)
        counts[result] = counts.get(result, 0) + 1
        if result.startswith("SKIPPED"):
            print(f"  {path}: {result}")
    for result, n in sorted(counts.items()):
        print(f"{result}: {n} file(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
