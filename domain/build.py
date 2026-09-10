# -*- coding: utf-8 -*-
"""build — inline the domain runtime + a course's glossary into its pages.

The walkthrough runtime's gate asks: *the evidence you cite must exist.* This
one asks its mirror image: **the vocabulary you use must be defined.**

Every word on the corpus's `watchlist` that actually appears in the course's
prose must resolve to a glossary term, or carry a written reason for not
needing one. Nothing else fails the build. A gate that infers jargon by
frequency and fails on ordinary English gets switched off within a week, so
discovery is a separate, advisory report: `--report` tells you what you are
still assuming, and you decide what goes on the watchlist.

Usage:
    python build.py --corpus docs/domain-corpus.json --root . \\
        --target course/index.html --prose course/index.html --prose-mode mods

    python build.py --corpus docs/domain-corpus.json --root . \\
        --prose course/index.html --prose-mode mods --check-only
    python build.py --corpus domain/corpus.json --root . \\
        --target "output/M*.html" --prose "output/M*.html" --prose-mode html

    --report      list undefined candidate jargon, ranked, as a watchlist stanza
    --check-only  run the gate and write nothing
"""
from __future__ import annotations

import argparse
import glob as globmod
import json
import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUNTIME_JS = HERE / "runtime.js"
RUNTIME_CSS = HERE / "runtime.css"

PLACEHOLDER = "<!-- DG:BUNDLE -->"
START = "<!-- DG:START -->"
END = "<!-- DG:END -->"

WT_START, WT_END = "<!-- WT:START -->", "<!-- WT:END -->"

# Deploy staging trees hold whole copies of OTHER courses — ultimate-context-eng's
# scripts/dist/courses/ contains knowledge-graph — so a scan that includes them
# reports another course's vocabulary as this one's.
EXCLUDE_DIRS = ("scripts/dist", "node_modules", ".venv", "archive", "dist/")


class BuildError(Exception):
    pass


# ------------------------------------------------------------------ corpus

def load_corpus(path: Path) -> dict:
    corpus = json.loads(path.read_text(encoding="utf-8"))
    glossary = corpus.get("glossary")
    if not glossary:
        raise BuildError(f"{path}: no glossary entries")

    seen: dict[str, str] = {}
    for entry in glossary:
        term = entry.get("term")
        if not term:
            raise BuildError(f"{path}: an entry has no 'term'")
        if not entry.get("short"):
            raise BuildError(f"{path}: '{term}' has no 'short'")
        for form in [term] + list(entry.get("match") or []):
            key = form.lower()
            if key in seen:
                raise BuildError(
                    f"{path}: surface form {form!r} is claimed by both "
                    f"{seen[key]!r} and {term!r} — the first one wins silently, "
                    f"so one of them must change")
            seen[key] = term

    _check_reachable(glossary, path)
    return corpus


def _regex(glossary: list[dict]) -> tuple[re.Pattern, dict]:
    """The same index the runtime builds: longest form first, so a compound
    wins over the word inside it."""
    by_form = {}
    forms = []
    for entry in glossary:
        for form in [entry["term"]] + list(entry.get("match") or []):
            by_form[form.lower()] = entry
            forms.append(form)
    forms.sort(key=len, reverse=True)
    alt = "|".join(re.escape(f) for f in forms)
    return re.compile(r"\b(" + alt + r")(s|es)?\b", re.I), by_form


def _check_reachable(glossary: list[dict], path: Path) -> None:
    """Every declared form must actually win its own match.

    A shorter term contained in a longer one is fine — longest-first ordering
    handles it. What is NOT fine is a form that can never be reached because
    some other entry always matches first; that entry would be dead on arrival
    and nobody would notice.
    """
    pattern, by_form = _regex(glossary)
    for entry in glossary:
        for form in [entry["term"]] + list(entry.get("match") or []):
            hit = pattern.search(form)
            if not hit or by_form[hit.group(1).lower()]["term"] != entry["term"]:
                won = by_form[hit.group(1).lower()]["term"] if hit else "nothing"
                raise BuildError(
                    f"{path}: surface form {form!r} of {entry['term']!r} is "
                    f"unreachable — {won!r} matches it first")


# ------------------------------------------------------------------- prose

def _strip_generated(html: str) -> str:
    for a, b in ((WT_START, WT_END), (START, END)):
        html = re.sub(re.escape(a) + r".*?" + re.escape(b), " ", html, flags=re.S)
    return html


def prose_from_html(path: Path) -> str:
    """What a reader of a standalone page actually reads."""
    html = _strip_generated(path.read_text(encoding="utf-8", errors="replace"))
    for tag in ("script", "style", "svg", "pre", "code"):
        html = re.sub(rf"<{tag}\b.*?</{tag}>", " ", html, flags=re.S | re.I)
    html = re.sub(r"<!--.*?-->", " ", html, flags=re.S)
    return re.sub(r"<[^>]+>", " ", html)


def prose_from_mods(path: Path) -> str:
    """What a reader of a kit-format player actually reads.

    The prose is not the HTML file — it is the strings inside `const MODS = [
    ... ];`. Reading the raw file instead would fold in the runtime, the
    walkthrough bundle and every CSS rule.
    """
    src = _strip_generated(path.read_text(encoding="utf-8", errors="replace")).replace("\r\n", "\n")
    try:
        i = src.index("const MODS = [") + len("const MODS = [")
        j = src.index("\n];", i)
    except ValueError:
        raise BuildError(f"{path}: no `const MODS = [ ... \\n];` array found — "
                         f"is this a kit-format player? try --prose-mode html")
    mods = json.loads("[" + src[i:j] + "]")

    out: list[str] = []

    def walk(value):
        if isinstance(value, str):
            out.append(value)
        elif isinstance(value, list):
            for v in value:
                walk(v)
        elif isinstance(value, dict):
            for v in value.values():
                walk(v)

    walk(mods)
    return re.sub(r"<[^>]+>", " ", " ".join(out))


def gather_prose(patterns: list[str], mode: str) -> tuple[str, list[Path]]:
    files: list[Path] = []
    for pattern in patterns:
        for hit in sorted(globmod.glob(pattern, recursive=True)):
            p = Path(hit)
            flat = p.as_posix()
            if any(x in flat for x in EXCLUDE_DIRS):
                continue
            if p.is_file():
                files.append(p)
    if not files:
        raise BuildError(f"no prose files matched {patterns}")
    reader = prose_from_mods if mode == "mods" else prose_from_html
    return " ".join(reader(p) for p in files), files


# -------------------------------------------------------------------- gate

def gate(corpus: dict, prose: str, corpus_path: Path) -> list[str]:
    """Hard failures only. Returns the list of problems; empty means pass."""
    problems: list[str] = []
    terms = {e["term"].lower() for e in corpus["glossary"]}
    for e in corpus["glossary"]:
        for f in e.get("match") or []:
            terms.add(f.lower())

    for item in corpus.get("watchlist") or []:
        word = item.get("word")
        if not word:
            problems.append(f"{corpus_path}: a watchlist item has no 'word'")
            continue
        hits = len(re.findall(r"\b" + re.escape(word) + r"\b", prose, re.I))
        if not hits:
            continue  # not used; nothing to demand
        if item.get("skip"):
            if not str(item["skip"]).strip():
                problems.append(
                    f"watchlist word {word!r} opts out with an empty reason — "
                    f"write why it needs no definition")
            continue
        target = (item.get("term") or word).lower()
        if target not in terms:
            problems.append(
                f"watchlist word {word!r} appears {hits} times in the course prose\n"
                f"      but resolves to no glossary term.\n"
                f"      Add a term to {corpus_path}, or opt it out with\n"
                f'        {{"word": "{word}", "skip": "<why this word needs no definition here>"}}')
    return problems


def orphans(corpus: dict, prose: str) -> list[str]:
    """Glossary entries the prose never uses. A reader will never meet them."""
    dead = []
    for e in corpus["glossary"]:
        forms = [e["term"]] + list(e.get("match") or [])
        if not any(re.search(r"\b" + re.escape(f) + r"\b", prose, re.I) for f in forms):
            dead.append(e["term"])
    return dead


STOP = set("""the a an and or but if then than that this these those of to in on at by for with
from as is are was were be been being it its it's they them their there here what which who whom
whose how why when where all any both each few more most other some such no nor not only own same
so too very can will just should now you your we our i he she his her him us do does did done have
has had having about into over under again further once during before after above below up down out
off between through against while because until also may might must shall would could one two three
first second next last new old good best better use used using make makes made get gets got go goes
going see sees seen say says said know knows known think thinks like likes want wants need needs
work works working way ways thing things time times part parts case cases point points fact facts
example examples number numbers people person course module modules read reads reading write writes
writing run runs running""".split())

CANDIDATE = re.compile(r"\b([A-Z]{2,}(?:-[A-Z0-9]+)?|[a-z]+(?:-[a-z]+)+)\b")


def report(corpus: dict, prose: str, minimum: int) -> None:
    """Advisory. Never fails a build — heuristics must not gate one."""
    known = set()
    for e in corpus["glossary"]:
        for f in [e["term"]] + list(e.get("match") or []):
            known.add(f.lower())
    for item in corpus.get("watchlist") or []:
        if item.get("word"):
            known.add(item["word"].lower())

    counts = Counter()
    for hit in CANDIDATE.findall(prose):
        low = hit.lower()
        if low in known or low in STOP or len(low) < 3:
            continue
        counts[hit] += 1

    rows = [(w, n) for w, n in counts.most_common() if n >= minimum]
    if not rows:
        print(f"report: no undefined candidate above {minimum} uses")
        return
    print(f"\nreport: {len(rows)} candidate term(s) used >= {minimum} times with no entry.")
    print("Paste what belongs, with a term or a written reason:\n")
    print('  "watchlist": [')
    for w, n in rows:
        print(f'    {{"word": "{w}", "term": "TODO"}},'.ljust(56) + f"// {n} uses")
    print("  ]")


# ---------------------------------------------------------------- bundling

def bundle(corpus: dict) -> str:
    css = RUNTIME_CSS.read_text(encoding="utf-8")
    js = RUNTIME_JS.read_text(encoding="utf-8")
    data = {k: v for k, v in corpus.items() if k in ("glossary",)}
    cfg = corpus.get("config") or {}
    cfg.setdefault("title", corpus.get("title", "Glossary"))
    cfg.setdefault("subtitle", corpus.get("subtitle", ""))
    payload = (
        js
        + "\nDG.configure(" + json.dumps(cfg, ensure_ascii=False, separators=(",", ":")) + ");"
        + "DG.register(" + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ");"
        + "DG.start();"
    ).replace("</script", r"<\/script")
    return (f"{START}\n<!-- generated by shared/domain/build.py — do not hand-edit -->\n"
            f"<style>{css}</style>\n<script>{payload}</script>\n{END}")


def inject(target: Path, block: str) -> None:
    src = target.read_text(encoding="utf-8")

    existing = re.search(re.escape(START) + r".*?" + re.escape(END), src, re.S)
    if existing:
        src = src[:existing.start()] + PLACEHOLDER + src[existing.end():]
    if PLACEHOLDER not in src:
        raise BuildError(f"{target}: neither {PLACEHOLDER} nor a previously generated "
                         f"block found — add the placeholder before </body>")

    # Our region must never land inside the walkthrough's.
    at = src.index(PLACEHOLDER)
    wt_a, wt_b = src.find(WT_START), src.find(WT_END)
    if wt_a != -1 and wt_b != -1 and wt_a < at < wt_b:
        raise BuildError(f"{target}: {PLACEHOLDER} sits inside the WT:START/WT:END "
                         f"bundle — move it after {WT_END}")

    out = src.replace(PLACEHOLDER, block)
    target.write_text(out, encoding="utf-8")
    kb = len(block.encode("utf-8")) / 1024
    print(f"  {target}  (+{kb:.1f} kB, page now {target.stat().st_size / 1024:.1f} kB)")


def collide(target: Path) -> list[str]:
    """Fail loudly rather than silently shadowing a host's own names."""
    src = _strip_generated(target.read_text(encoding="utf-8", errors="replace"))
    bad = []
    for needle in ("dg-chip", "data-dg-", "window.DG", "DG.register"):
        if needle in src:
            bad.append(f"{target}: already contains {needle!r} outside a generated block")
    return bad


# -------------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--root", default=".")
    ap.add_argument("--target", action="append", default=[],
                    help="page(s) to inject into; globs allowed, repeatable")
    ap.add_argument("--prose", action="append", default=[],
                    help="page(s) to read the course's prose from (default: --target)")
    ap.add_argument("--prose-mode", choices=("mods", "html"), default="html")
    ap.add_argument("--check-only", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--report-min", type=int, default=15)
    args = ap.parse_args()

    corpus_path = Path(args.corpus)
    try:
        corpus = load_corpus(corpus_path)
    except BuildError as exc:
        print(f"BUILD FAILED: {exc}")
        return 1
    print(f"corpus: {len(corpus['glossary'])} terms from {corpus_path}")

    try:
        prose, files = gather_prose(args.prose or args.target, args.prose_mode)
    except BuildError as exc:
        print(f"BUILD FAILED: {exc}")
        return 1
    print(f"prose:  {len(files)} file(s), {len(prose.split()):,} words ({args.prose_mode} mode)")

    problems = gate(corpus, prose, corpus_path)
    for p in problems:
        print(f"BUILD FAILED: {p}")

    dead = orphans(corpus, prose)
    if dead:
        print(f"note: {len(dead)} glossary term(s) never used in prose: {', '.join(dead)}")

    for path in [e.get("source") for e in corpus["glossary"] if e.get("source")]:
        if not (Path(args.root) / str(path).split("#")[0]).exists():
            print(f"BUILD FAILED: source {path!r} does not resolve under {args.root}")
            problems.append(path)

    if args.report:
        report(corpus, prose, args.report_min)

    if problems:
        return 1
    print("gate: pass")

    if args.check_only:
        print("--check-only: nothing written")
        return 0
    if not args.target:
        return 0

    targets: list[Path] = []
    for pattern in args.target:
        targets += [Path(h) for h in sorted(globmod.glob(pattern, recursive=True))
                    if not any(x in Path(h).as_posix() for x in EXCLUDE_DIRS)]
    if not targets:
        print(f"BUILD FAILED: no target matched {args.target}")
        return 1

    clashes = [c for t in targets for c in collide(t)]
    if clashes:
        for c in clashes:
            print(f"BUILD FAILED: {c}")
        return 1

    block = bundle(corpus)
    print(f"embedding into {len(targets)} page(s):")
    for t in targets:
        inject(t, block)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BuildError as exc:
        print(f"BUILD FAILED: {exc}")
        sys.exit(1)
