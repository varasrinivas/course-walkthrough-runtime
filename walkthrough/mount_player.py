"""mount_player — add a walkthrough mount point to a kit-format course player.

The kit-format players (context-eng-kit, ultimate-context-eng) hold every
module in a `const MODS = [ ... ]` array inside a single index.html, and render
a `content` section's `body` as raw HTML. So a walkthrough needs no player
change at all: insert one more `content` section whose body is the bridge
sentence plus a `<div data-wt="...">`, and the runtime mounts into it.

Following the house rule ("NEVER rewrite the full HTML file — use Python to
inject module data"), this splices text: the new section object is inserted
immediately before the module's first quiz section, so the walkthrough lands
after the teaching and before the check. Nothing else in the file moves.

Idempotent: a module that already carries the mount is skipped.

Usage:
  python mount_player.py --html course/index.html --module U02 \
      --scenario uce-baseline-receipt \
      --title "Walk it, step by step" \
      --bridge "Below is that first measurement, step by step ..."
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

PLACEHOLDER = "<!-- WT:BUNDLE -->"


def mods_span(html: str) -> tuple[int, int]:
    start = html.index("const MODS = [") + len("const MODS = [")
    end = html.index("\n];", start)
    return start, end


def module_span(html: str, start: int, end: int, module_id: str) -> tuple[int, int]:
    key = f'"id": "{module_id}"'
    i = html.find(key, start, end)
    if i < 0:
        raise SystemExit(f"module {module_id} not found in MODS")
    nxt = re.search(r'\n  "id": "', html[i + len(key):end])
    # Modules are the only objects carrying an "id" at this indent level.
    j = html.find('"id": "', i + len(key), end)
    return i, (j if j > 0 else end)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--html", required=True)
    ap.add_argument("--module", required=True)
    ap.add_argument("--scenario", required=True)
    ap.add_argument("--title", default="Walk it, step by step")
    ap.add_argument("--bridge", required=True, help="one sentence naming what to watch for")
    ap.add_argument("--theme", default="", help='"dark" for dark-themed hosts')
    args = ap.parse_args()

    path = Path(args.html)
    html = path.read_text(encoding="utf-8")

    mount = (f'<div data-wt="{args.scenario}"'
             + (f' data-wt-theme="{args.theme}"' if args.theme else "") + '></div>')
    # The section is stored inside MODS via json.dumps, so the mount lands in the
    # file with its quotes escaped. Checking only the raw form made this
    # non-idempotent on kit-format players: a second run appended a duplicate
    # section instead of skipping. Check both forms.
    if mount in html or json.dumps(mount)[1:-1] in html:
        print(f"{args.module}: already mounted, skipping")
        return 0

    start, end = mods_span(html)
    m0, m1 = module_span(html, start, end, args.module)

    q = html.find('"type": "quiz"', m0, m1)
    if q < 0:
        raise SystemExit(f"{args.module}: no quiz section to anchor against")
    # back up to the opening brace of that section object
    brace = html.rfind("{", m0, q)
    if brace < 0:
        raise SystemExit(f"{args.module}: could not find the section's opening brace")

    section = {
        "type": "content",
        "title": args.title,
        "body": f"<p>{args.bridge}</p>\n{mount}",
    }
    text = json.dumps(section, indent=2, ensure_ascii=False)
    text = "\n".join(("    " + ln) if i else ln for i, ln in enumerate(text.split("\n")))

    html = html[:brace] + text + ",\n    " + html[brace:]

    if PLACEHOLDER not in html and "<!-- WT:START -->" not in html:
        html = html.replace("</body>", f"{PLACEHOLDER}\n</body>", 1)
        print("  added the WT:BUNDLE placeholder before </body>")

    path.write_text(html, encoding="utf-8")

    # The array must still parse, or the player renders nothing at all.
    check = path.read_text(encoding="utf-8")
    s, e = mods_span(check)
    mods = json.loads("[" + check[s:e].strip() + "]")
    ids = [m["id"] for m in mods]
    hit = next(m for m in mods if m["id"] == args.module)
    titles = [x.get("title") for x in hit["sections"] if x["type"] == "content"]
    print(f"{args.module}: mounted {args.scenario} · MODS parses ({len(ids)} modules) · "
          f"sections now end with {titles[-1]!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
