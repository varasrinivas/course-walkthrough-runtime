# -*- coding: utf-8 -*-
"""harvest — seed a corpus from the definitions a course already wrote by hand.

Some courses already mandate a definition on first use and carry the result
inline, e.g. knowledge-graph's

    <span class="term-tooltip" tabindex="0">OKF<span class="tooltip-content">…</span></span>

Fifty-odd of those are a glossary that was never collected: the same word gets
re-defined by hand in each module that mentions it, the copies drift, and a
reader in the module that DIDN'T define it is still stuck. This pulls them into
one corpus so the runtime can serve every module from a single definition.

It writes a DRAFT. Merged duplicates are reported rather than silently
resolved, because two hand-written definitions of one word may disagree, and
which one is right is an editorial call.

Usage:
    python harvest.py --html "output/*.html" --out domain/corpus.draft.json
    python harvest.py --html "output/*.html" --out - --min-len 40
"""
from __future__ import annotations

import argparse
import glob as globmod
import html as htmlmod
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

# <span class="term-tooltip" …>TERM<span class="tooltip-content" …>DEFINITION</span></span>
TOOLTIP = re.compile(
    r'<span[^>]*class="[^"]*\bterm-tooltip\b[^"]*"[^>]*>'
    r'(?P<term>.*?)'
    r'<span[^>]*class="[^"]*\btooltip-content\b[^"]*"[^>]*>'
    r'(?P<def>.*?)</span>',
    re.S | re.I,
)


def clean(fragment: str) -> str:
    return re.sub(r"\s+", " ", htmlmod.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def split_sentences(text: str) -> tuple[str, str]:
    """First sentence becomes `short`, the rest `long` — the corpus shape the
    runtime renders in the popover."""
    parts = re.split(r"(?<=[.!?])\s+", text, maxsplit=1)
    head = parts[0].strip()
    tail = parts[1].strip() if len(parts) > 1 else ""
    return head, tail


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--html", action="append", required=True, help="glob(s) to scan")
    ap.add_argument("--out", required=True, help="draft corpus path, or - for stdout")
    ap.add_argument("--min-len", type=int, default=20,
                    help="ignore definitions shorter than this (default 20)")
    args = ap.parse_args()

    files: list[Path] = []
    for pattern in args.html:
        files += [Path(h) for h in sorted(globmod.glob(pattern, recursive=True))
                  if Path(h).is_file()]
    if not files:
        print(f"nothing matched {args.html}")
        return 1

    found: dict[str, list[tuple[str, str]]] = defaultdict(list)   # term -> [(def, file)]
    for path in files:
        src = path.read_text(encoding="utf-8", errors="replace")
        for m in TOOLTIP.finditer(src):
            term, definition = clean(m.group("term")), clean(m.group("def"))
            if not term or len(definition) < args.min_len:
                continue
            found[term].append((definition, path.name))

    if not found:
        print("no .term-tooltip definitions found")
        return 1

    glossary, conflicts, merged = [], [], []
    for term in sorted(found, key=str.lower):
        variants = found[term]
        texts = {d for d, _ in variants}
        if len(texts) > 1:
            conflicts.append((term, [(d[:70], f) for d, f in variants]))
        elif len(variants) > 1:
            merged.append((term, len(variants)))
        short, long = split_sentences(variants[0][0])
        entry = {"term": term, "short": short}
        if long:
            entry["long"] = long
        glossary.append(entry)

    # Terms that differ only by plural or case are one entry with a `match`.
    by_key: dict[str, dict] = {}
    folded = []
    for entry in glossary:
        key = re.sub(r"e?s$", "", entry["term"].lower())
        if key in by_key and by_key[key]["term"].lower() != entry["term"].lower():
            by_key[key].setdefault("match", []).append(entry["term"])
            folded.append(entry["term"] + " -> " + by_key[key]["term"])
        else:
            by_key.setdefault(key, entry)
    glossary = [e for e in glossary if e in by_key.values()]

    draft = {
        "_comment": ("DRAFT harvested by shared/domain/harvest.py from the course's existing "
                     ".term-tooltip definitions. Review before use: `short` is the first "
                     "sentence of each hand-written tooltip, acronyms still need `match` "
                     "entries, and any conflict listed at harvest time was resolved by taking "
                     "the first occurrence."),
        "title": "Glossary",
        "subtitle": "Every domain word this course uses.",
        "config": {},
        "watchlist": [],
        "glossary": glossary,
    }

    text = json.dumps(draft, indent=2, ensure_ascii=False) + "\n"
    if args.out == "-":
        sys.stdout.write(text)
    else:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text, encoding="utf-8", newline="\n")

    print(f"scanned {len(files)} file(s)")
    print(f"harvested {len(glossary)} term(s) from {sum(len(v) for v in found.values())} tooltips")
    for term, n in merged:
        print(f"  merged {n} identical copies of {term!r}")
    for term in folded:
        print(f"  folded {term}")
    for term, variants in conflicts:
        print(f"  CONFLICT {term!r} is defined differently in {len(variants)} places:")
        for d, f in variants:
            print(f"      {f}: {d}…")
    if args.out != "-":
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
