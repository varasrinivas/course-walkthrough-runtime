"""build — inline the walkthrough runtime + scenarios into a course page.

Two outputs, one scenario set (the priorauth-sdd-course discipline):

  1. embedded   the learning path — the bundle is injected into a course page
                at its `<!-- WT:BUNDLE -->` placeholder, and every
                `<div data-wt="scenario-id">` in that page becomes a
                step-through walkthrough.
  2. standalone the quick reference — one page, every scenario behind a tab.

The honesty gate: a scenario whose provenance is "measured" must cite a source
file that actually exists. A broken citation fails the build rather than
shipping a number nobody can trace. Scenarios marked "illustrative" are allowed
without a source but must say so, and the runtime prints that label on screen.

Usage:
  python build.py --target course/index.html --scenarios walkthroughs/*.json \
                  --root . [--out course/index.html]
  python build.py --standalone walkthrough/index.html --scenarios walkthroughs/*.json \
                  --root . --title "Knowledge Graphs — walkthroughs"

`--target` edits in place unless `--out` is given. Pass `--source-suffix .src`
to read `index.src.html` and write `index.html` (generated-from-source split).
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).parent
RUNTIME_JS = HERE / "runtime.js"
RUNTIME_CSS = HERE / "runtime.css"
PLACEHOLDER = "<!-- WT:BUNDLE -->"
START = "<!-- WT:START -->"
END = "<!-- WT:END -->"

VALID_KINDS = {"prompt", "claude", "tool", "out", "out-pass", "out-fail", "gate"}
VALID_VIEWS = {"json", "spec", "rows", "diff", "tests", "note", "stack",
               "receipt", "bars", "window"}


class BuildError(Exception):
    """Anything that should stop the build rather than ship silently."""


# --------------------------------------------------------------- loading

def load_scenarios(paths: list[Path]) -> list[dict]:
    # Order is the caller's: it decides tab order on the standalone page, so a
    # course can present its scenarios in teaching order rather than filename
    # order. A glob argument is sorted; several explicit paths are not.
    out, seen = [], {}
    for p in paths:
        try:
            obj = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise BuildError(f"{p}: invalid JSON — {e}") from e
        for sc in (obj if isinstance(obj, list) else [obj]):
            sid = sc.get("id")
            if not sid:
                raise BuildError(f"{p}: a scenario has no id")
            if sid in seen:
                raise BuildError(f"duplicate scenario id {sid!r} in {p} and {seen[sid]}")
            seen[sid] = p
            sc["_file"] = str(p)
            out.append(sc)
    return out


# ------------------------------------------------------------ validation

def validate(scenarios: list[dict], root: Path) -> list[str]:
    """Structural checks plus the provenance gate. Returns info lines."""
    notes = []
    for sc in scenarios:
        where = f"{sc.get('id')} ({sc.get('_file')})"

        steps = sc.get("steps")
        if not steps:
            raise BuildError(f"{where}: no steps")

        prov = sc.get("provenance")
        if not prov or "kind" not in prov:
            raise BuildError(
                f"{where}: missing provenance. Every scenario must declare "
                f'{{"kind": "measured", "source": "..."}} or {{"kind": "illustrative"}}.')
        kind = prov["kind"]
        if kind not in ("measured", "illustrative"):
            raise BuildError(f"{where}: provenance.kind must be measured or illustrative")

        if kind == "measured":
            src = prov.get("source")
            if not src:
                raise BuildError(f"{where}: measured provenance needs a source file")
            # A source may name several files, comma-separated, each optionally
            # followed by "#..." naming the rows within it.
            for part in [s.strip() for s in src.split(",") if s.strip()]:
                rel = part.split("#", 1)[0].strip()
                if not (root / rel).exists():
                    raise BuildError(
                        f"{where}: cites {rel!r}, which does not exist under {root}. "
                        f"Fix the citation or mark the scenario illustrative.")
            notes.append(f"  {sc['id']}: measured <- {src}")
        else:
            notes.append(f"  {sc['id']}: illustrative")

        for i, st in enumerate(steps, 1):
            if not st.get("title"):
                raise BuildError(f"{where} step {i}: no title")
            # A step may cite its own measured source — used where a narrated
            # scenario pays off with real numbers. Gated exactly like the
            # scenario-level citation.
            if st.get("source"):
                for part in [s.strip() for s in st["source"].split(",") if s.strip()]:
                    rel = part.split("#", 1)[0].strip()
                    if not (root / rel).exists():
                        raise BuildError(
                            f"{where} step {i}: cites {rel!r}, which does not exist "
                            f"under {root}.")
                notes.append(f"    step {i} measured <- {st['source']}")
            for ln in st.get("terminal") or []:
                if ln.get("kind") not in VALID_KINDS:
                    raise BuildError(
                        f"{where} step {i}: terminal line kind {ln.get('kind')!r} "
                        f"not one of {sorted(VALID_KINDS)}")
            state = st.get("state")
            if state:
                for side in ("before", "after"):
                    pane = state.get(side)
                    if not pane:
                        continue
                    _check_view(pane.get("view"), f"{where} step {i} {side}")
    return notes


def _check_view(view, where: str) -> None:
    if not view:
        return
    t = view.get("type")
    if t not in VALID_VIEWS:
        raise BuildError(f"{where}: view type {t!r} not one of {sorted(VALID_VIEWS)}")
    if t == "stack":
        for sub in view.get("views") or []:
            _check_view(sub, where)


# -------------------------------------------------------------- bundling

def bundle(scenarios: list[dict]) -> str:
    """The inlinable <style>+<script> block. Self-contained, no external refs."""
    css = RUNTIME_CSS.read_text(encoding="utf-8")
    js = RUNTIME_JS.read_text(encoding="utf-8")
    clean = [{k: v for k, v in sc.items() if not k.startswith("_")} for sc in scenarios]
    data = json.dumps(clean, ensure_ascii=False, separators=(",", ":"))
    # A literal </script> inside the data or the runtime would close the tag early.
    payload = (js + "\nWT.register(" + data + ");WT.mountAll();").replace("</script", r"<\/script")
    return (f"{START}\n<!-- generated by shared/walkthrough/build.py — do not hand-edit -->\n"
            f"<style>{css}</style>\n<script>{payload}</script>\n{END}")


def inject(target: Path, block: str, scenarios: list[dict], out: Path) -> None:
    src = target.read_text(encoding="utf-8")
    # Rebuilds replace the previously generated block; the placeholder is only
    # needed the first time. Without this, a second build would have nowhere
    # to write and the page would keep shipping stale scenario data.
    existing = re.search(re.escape(START) + r".*?" + re.escape(END), src, re.S)
    if existing:
        src = src[:existing.start()] + PLACEHOLDER + src[existing.end():]
    if PLACEHOLDER not in src:
        raise BuildError(f"{target}: neither {PLACEHOLDER} nor a previously generated "
                         f"block found — add the placeholder before </body>")

    # Mounts appear as plain HTML in a static page, and with escaped quotes when
    # they sit inside a JSON string in a kit-format player's MODS array.
    ids = set(re.findall(r'data-wt=\\?"([^"\\]+)', src))
    known = {sc["id"] for sc in scenarios}
    unknown = ids - known
    if unknown:
        raise BuildError(f"{target}: mount points reference unknown scenarios: "
                         f"{sorted(unknown)}")
    if not ids:
        raise BuildError(f"{target}: no data-wt mount points — nothing would render")

    out.write_text(src.replace(PLACEHOLDER, block), encoding="utf-8")
    kb = len(block.encode("utf-8")) / 1024
    total = out.stat().st_size / 1024
    print(f"embedded -> {out}")
    print(f"  mount points: {len(ids)} ({', '.join(sorted(ids))})")
    print(f"  bundle {kb:.1f} kB · page now {total:.1f} kB")


STANDALONE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:#F2F4F7;color:#1C2127;font-family:system-ui,-apple-system,'Segoe UI',sans-serif;line-height:1.6}}
.page{{max-width:1100px;margin:0 auto;padding:2.2rem 1.5rem 5rem}}
.topbar{{display:flex;justify-content:space-between;align-items:center;gap:1rem;margin-bottom:1.6rem;flex-wrap:wrap}}
.topbar a{{font-family:'JetBrains Mono',monospace;font-size:.8rem;color:#33506B;text-decoration:none;
  border:1px solid #D9DEE5;background:#fff;border-radius:8px;padding:.4rem .8rem}}
.topbar a:hover{{border-color:#1C2127}}
.eyebrow{{font-family:'JetBrains Mono',monospace;font-size:.7rem;letter-spacing:.14em;
  text-transform:uppercase;color:#4A5361}}
h1{{font-size:1.9rem;line-height:1.2;margin:.3rem 0 .5rem;letter-spacing:-.02em}}
.lede{{color:#4A5361;max-width:70ch;margin-bottom:1.8rem}}
</style>
</head>
<body>
<div class="page">
  <div class="topbar">
    <a href="{back}">← {back_label}</a>
    <span class="eyebrow">quick reference</span>
  </div>
  <div class="eyebrow">{eyebrow}</div>
  <h1>{title}</h1>
  <p class="lede">{lede}</p>
  <div id="wt-standalone"></div>
</div>
{bundle}
<script>WT.standalone(document.getElementById('wt-standalone'));</script>
</body>
</html>
"""


def build_standalone(out: Path, scenarios: list[dict], title: str, lede: str,
                     eyebrow: str, back: str, back_label: str,
                     copy_assets: str | None = None) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    page = STANDALONE.format(title=title, lede=lede, eyebrow=eyebrow, back=back,
                             back_label=back_label, bundle=bundle(scenarios))
    out.write_text(page, encoding="utf-8")
    print(f"standalone -> {out} ({out.stat().st_size / 1024:.1f} kB, "
          f"{len(scenarios)} scenarios)")

    # A scenario may reference images with a page-relative path (assets/x.png).
    # That resolves inside the course player but not beside the standalone page,
    # which lives one directory down. Copy them so both pages resolve the same
    # href instead of asking scenarios to know where they are being rendered.
    if copy_assets:
        src = Path(copy_assets)
        if not src.is_dir():
            raise BuildError(f"--copy-assets: {src} is not a directory")
        dst = out.parent / "assets"
        dst.mkdir(exist_ok=True)
        n = 0
        for f in sorted(src.iterdir()):
            if f.is_file():
                shutil.copy(f, dst / f.name)
                n += 1
        print(f"  copied {n} asset(s) -> {dst}")

    # Whatever the scenarios reference must actually be there.
    refs = set(re.findall(r'src=\\?"([^"\\]+)', json.dumps(scenarios)))
    missing = [r for r in refs
               if not r.startswith(("http://", "https://", "data:"))
               and not (out.parent / r).exists()]
    if missing:
        raise BuildError(
            f"{out}: references {len(missing)} file(s) that do not exist beside it: "
            f"{sorted(missing)[:5]}. Pass --copy-assets, or fix the path.")


# ------------------------------------------------------------------- cli

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scenarios", nargs="+", required=True, help="scenario JSON files")
    ap.add_argument("--root", default=".", help="repo root that provenance paths resolve against")
    ap.add_argument("--target", help="course page carrying <!-- WT:BUNDLE --> and data-wt mounts")
    ap.add_argument("--out", help="write the embedded build here (default: in place)")
    ap.add_argument("--standalone", help="also write the tabbed quick-reference page here")
    ap.add_argument("--title", default="Walkthroughs")
    ap.add_argument("--lede", default="Step through each scenario: what you type, what the "
                                      "agent answers, and how the state changes.")
    ap.add_argument("--eyebrow", default="walkthroughs")
    ap.add_argument("--back", default="../index.html")
    ap.add_argument("--back-label", default="Course")
    ap.add_argument("--copy-assets", default=None,
                    help="directory to copy beside the standalone page as assets/")
    ap.add_argument("--check-only", action="store_true", help="validate, build nothing")
    args = ap.parse_args()

    try:
        stream = sys.stdout
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

        root = Path(args.root).resolve()
        paths = []
        for pat in args.scenarios:
            p = Path(pat)
            paths.extend(sorted(p.parent.glob(p.name)) if "*" in p.name else [p])
        missing = [p for p in paths if not p.exists()]
        if missing:
            raise BuildError(f"scenario file(s) not found: {missing}")

        scenarios = load_scenarios(paths)
        notes = validate(scenarios, root)
        print(f"{len(scenarios)} scenario(s) validated against {root}")
        for n in notes:
            print(n)
        if args.check_only:
            return 0

        if not args.target and not args.standalone:
            raise BuildError("nothing to build — pass --target and/or --standalone")

        block = bundle(scenarios)
        if args.target:
            target = Path(args.target)
            inject(target, block, scenarios, Path(args.out) if args.out else target)
        if args.standalone:
            build_standalone(Path(args.standalone), scenarios, args.title, args.lede,
                             args.eyebrow, args.back, args.back_label, args.copy_assets)
        return 0

    except BuildError as e:
        print(f"\nBUILD FAILED: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
