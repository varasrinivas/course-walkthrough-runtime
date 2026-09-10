# -*- coding: utf-8 -*-
"""check — hold worked-example figures to the closed vocabulary.

A figure exists because a course anchored on a domain owes the reader the
artefact rather than a description of it. The vocabulary is closed so that every
figure in every course themes correctly, survives a redesign, and cannot quietly
become bespoke markup that only looks right today.

Enforced (each a hard failure):
  * only classes from the vocabulary below
  * at least one of them — prose with no figure class is not a figure
  * no inline style=, no hardcoded #hex (numeric entities like &#9660; are fine)
  * no links or cross-course tags — a figure routes nowhere
  * every id it cites resolves in the course's data file, when one is given

Usage:
    python check.py --figures docs/figures.json
    python check.py --figures docs/figures.json --ids bench/seed/dataset.json \\
        --id-pattern "PA-[0-9]{4}"
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

VOCAB = {
    "ue-fig", "ue-label", "ue-title", "ue-body", "ue-cap",
    "ue-rec", "ue-rec-h", "ue-f", "ue-fk", "ue-fv", "ue-ann", "ue-mark",
    "ue-cols", "ue-panel", "ue-panel-h",
    "ue-layers", "ue-layer", "ue-l1", "ue-l2", "ue-l3", "ue-l4", "ue-l5",
    "ue-lname", "ue-lnote",
    "ue-out", "ue-ok", "ue-bad",
    "ue-tab", "t-mono", "t-ok", "t-bad",
    "ue-tok", "ue-arrow", "ue-note",
}

# A figure that links out stops being a figure and becomes navigation.
ROUTES = re.compile(r"<a\s|\[(?:Agent|SDLC|CE|KG|Platform)\s+[A-Z]?\d|href=")


def check_body(body: str, where: str, ids: set[str] | None, pattern: str | None) -> list[str]:
    problems = []
    classes = set()
    for hit in re.findall(r'class="([^"]*)"', body):
        classes.update(hit.split())

    unknown = sorted(c for c in classes if c not in VOCAB)
    if unknown:
        problems.append(f"{where}: class outside the vocabulary: {', '.join(unknown)}")
    if not any(c.startswith(("ue-", "t-")) for c in classes):
        problems.append(f"{where}: no figure class — this is prose, not a figure")
    if re.search(r"\sstyle\s*=", body):
        problems.append(f"{where}: inline style= (use the vocabulary)")
    # not preceded by & — numeric HTML entities are not colours
    if re.search(r"(?:^|[^&\w])#[0-9a-fA-F]{3,8}\b", body):
        problems.append(f"{where}: hardcoded colour (the palette is themed for you)")
    if ROUTES.search(body):
        problems.append(f"{where}: a figure routes nowhere — no links, no cross-course tags")

    if ids is not None and pattern:
        cited = set(re.findall(pattern, body))
        missing = sorted(cited - ids)
        if missing:
            problems.append(f"{where}: id(s) not in the course data: {', '.join(missing)}")
    return problems


def collect_ids(path: Path, pattern: str) -> set[str]:
    return set(re.findall(pattern, path.read_text(encoding="utf-8", errors="replace")))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--figures", required=True, help="JSON: {key: {title, body, caption}}")
    ap.add_argument("--ids", help="file whose ids a figure may cite")
    ap.add_argument("--id-pattern", help="regex for those ids, e.g. 'PA-[0-9]{4}'")
    args = ap.parse_args()

    figures = json.loads(Path(args.figures).read_text(encoding="utf-8"))
    ids = collect_ids(Path(args.ids), args.id_pattern) if (args.ids and args.id_pattern) else None
    if ids is not None:
        print(f"ids: {len(ids)} resolvable from {args.ids}")

    problems: list[str] = []
    n = 0
    for key, fig in figures.items():
        if key.startswith("_"):
            continue
        n += 1
        if not fig.get("title"):
            problems.append(f"{key}: no title")
        if not fig.get("caption"):
            problems.append(f"{key}: no caption — say what to notice")
        body = fig.get("body") or ""
        if not body:
            problems.append(f"{key}: no body")
            continue
        problems += check_body(body, key, ids, args.id_pattern)

    for p in problems:
        print(f"FAILED: {p}")
    if problems:
        return 1
    print(f"ok: {n} figure(s), all inside the vocabulary")
    return 0


if __name__ == "__main__":
    sys.exit(main())
