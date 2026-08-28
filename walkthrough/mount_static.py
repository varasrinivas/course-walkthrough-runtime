"""mount_static — add a walkthrough mount point to a self-contained module page.

For courses where each module is one standalone HTML file (knowledge-graph).
The mount goes at the END of the section it belongs to, under the standing
ritual borrowed from priorauth-sdd-course:

    <h3>Walk it, step by step</h3>
    <p>one bespoke sentence naming what to watch for</p>
    <div data-wt="scenario-id" data-wt-theme="dark"></div>

and `<!-- WT:BUNDLE -->` once before </body>, which `build.py` then fills.

Idempotent: a page that already carries the mount is skipped.

Usage:
  python mount_static.py --html output/M04-graphify-in-practice.html \
      --section querying --scenario kg-graphify-run --theme dark \
      --bridge "Below is that pipeline end to end …"
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

PLACEHOLDER = "<!-- WT:BUNDLE -->"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--html", required=True)
    ap.add_argument("--section", required=True, help="id of the section to append to")
    ap.add_argument("--scenario", required=True)
    ap.add_argument("--title", default="Walk it, step by step")
    ap.add_argument("--bridge", required=True)
    ap.add_argument("--theme", default="")
    args = ap.parse_args()

    path = Path(args.html)
    html = path.read_text(encoding="utf-8")

    mount = (f'<div data-wt="{args.scenario}"'
             + (f' data-wt-theme="{args.theme}"' if args.theme else "") + "></div>")
    if mount in html:
        print(f"{path.name}: already mounted, skipping")
        return 0

    m = re.search(rf'<section[^>]*id="{re.escape(args.section)}"[^>]*>', html)
    if not m:
        raise SystemExit(f"{path.name}: no section with id={args.section!r}")
    close = html.find("</section>", m.end())
    if close < 0:
        raise SystemExit(f"{path.name}: section {args.section!r} is never closed")

    block = (f"\n  <h3>{args.title}</h3>\n"
             f"  <p>{args.bridge}</p>\n"
             f"  {mount}\n")
    html = html[:close] + block + html[close:]

    if PLACEHOLDER not in html and "<!-- WT:START -->" not in html:
        html = html.replace("</body>", f"{PLACEHOLDER}\n</body>", 1)
        print("  added the WT:BUNDLE placeholder before </body>")

    path.write_text(html, encoding="utf-8")
    print(f"{path.name}: mounted {args.scenario} at the end of #{args.section}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
