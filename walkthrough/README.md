# Walkthrough runtime

An interactive, step-by-step re-enactment that sits **inside** a course module:
what you type, what the agent answers, and how the state changes before and
after each step. Ported from `priorauth-sdd-course/walkthrough/`, which proved
the pattern — with one change: no React, so the bundle is small enough to inline
into sixteen separate module files instead of one guide page.

Used by `knowledge-graph`, `ultimate-context-eng` and `context-eng-kit`.

## Why re-enact instead of screenshot

Screenshots go stale, can't be searched or diffed, don't reflow on a phone, and
are banned outright by two of these courses' asset rules. A re-enactment is
data: the terminal is a list of typed lines, the "screen" is a small tagged
union of renderers. It restyles with the host page and weighs nothing.

## Files

| File | What |
|---|---|
| `runtime.js` | mount + step shell + terminal + state panel (~24 kB, no dependencies) |
| `runtime.css` | every rule scoped under `.wt`; light palette plus `.wt-dark` |
| `build.py` | validate, then inline runtime + scenarios into a page and/or a standalone page |
| `mount_player.py` | add a mount point to a kit-format player's `MODS` array |

## Authoring a scenario

One JSON file per scenario. Content is data — adding a step is a data edit, not
a code change.

```jsonc
{
  "id": "kg-147-files",            // matches <div data-wt="kg-147-files">
  "badge": "WALKTHROUGH",
  "color": "#D4A843",              // per-scenario accent (--scen-color)
  "time": "~4 min",
  "title": "The 147-file bug fix",
  "spec": "M00 · exploration vs reasoning",   // standalone view only
  "intro": "…",                                // standalone view only
  "provenance": { "kind": "measured", "source": "bench/results/grid.json#Q9" },
  "foot": "Run it for real: …",                // embedded view footer
  "steps": [ { /* see below */ } ]
}
```

A step pairs **intent** (left) with **evidence** (right):

```jsonc
{
  "title": "Escape at 147",
  "narrative": ["<p>-worth of HTML", "…"],
  "youDo": "a real command the learner can run",
  "claudeSays": "what the model mechanically does",
  "source": "path/to/data.json#row",        // optional per-step citation
  "terminal": [ { "kind": "prompt", "text": "…" } ],
  "state": {
    "label": "context window · turn 12",
    "before": { "title": "BEFORE — …", "view": { } },
    "after":  { "title": "AFTER — …",  "view": { } }   // omit for a single pane
  }
}
```

`narrative`, `youDo`, `claudeSays`, `note` and table cells are **HTML strings**
(trusted — you author them). Escape a literal `&` as `&amp;`.

### Terminal line kinds

| kind | Renders as |
|---|---|
| `prompt` | what you type — green `›`, types out character by character |
| `claude` | the model's reply — amber `⏺` |
| `tool` | a tool or shell invocation — blue `⚒` |
| `out` | neutral output |
| `out-pass` | green success |
| `out-fail` | red failure |
| `gate` | amber — a stop-and-decide moment (approval gate, grading gate) |

### View types

| type | For |
|---|---|
| `json` | an API response or record; `highlight: ["key"]` marks the fields that changed |
| `rows` | a table; per-row `tone: "win"\|"bad"` or `new: true` for an appended row |
| `diff` | a source diff; lines are `["p"\|"m"\|"a", "text"]` (plain / removed / added) |
| `tests` | a BUILD SUCCESS / BUILD FAILURE panel |
| `spec` | a spec card with a status stamp |
| `receipt` | a Token Lens: layered bar, itemised lines, cost chips, verdict stamp |
| `bars` | comparative totals across arms or strategies |
| `window` | a context window's layer composition against its capacity |
| `note` | a sentence |
| `stack` | several views in one pane |

Annotation is always a **data flag** — `highlight`, `tone`, `new` — never a mark
drawn on a picture.

## The honesty gate

Every scenario declares its provenance, and `build.py` enforces it:

- `{"kind": "measured", "source": "path#row"}` — the file **must exist** under
  `--root`. A citation that does not resolve fails the build.
- `{"kind": "illustrative", "source": "one line saying what it is"}` — allowed
  without data, and the runtime prints an ILLUSTRATIVE label on screen so a
  reader can never mistake a narrated example for a measurement.

A step may carry its own `source`, so a narrated scenario can pay off with real
numbers and have those numbers gated individually. That is what
`knowledge-graph/walkthroughs/M00-147-files.json` does.

### The second half: replayed lines must still say what they said

A resolving path is not the same as a truthful walkthrough. The failure it misses
is the one that actually happens: somebody edits the source, the replayed grep
output in the answer key keeps the old text, and nothing complains because the
path still resolves. A walkthrough exists to show the reader the answer, so a
stale one is worse than none.

So wherever an output line (`out`, `out-pass`, `out-fail`) replays a source line
in the shape `path:NN  content`, and `path` is one the scenario already cites,
`build.py` reads line NN and requires the shown content to be in it:

```
BUILD FAILED: cc-ep33-eager-meter step 3: shows src/components/RushMeter.jsx:13 as
    refetchInterval: 300, // lunch moves fast — never show a stale queue
  but that line reads
    refetchInterval: 500, // lunch moves fast — never show a stale queue
  Re-measure it, or stop citing the line.
```

Citing a line past the end of the file fails the same way.

Two deliberate accommodations: content after an `…` or `...` is treated as
elided, because trimming a long line to fit the card is honest; and a shown
fragment under 12 characters is ignored as too short to be a quotation.

**What it does not check.** Numbers a step computes, prose it writes, and output
no source file contains — a wallet balance, a test count, an API response body.
Those are still only as good as the person who measured them. The check is
narrow on purpose: it never fails a scenario that is telling the truth, so a
failure always means something is genuinely wrong.


## Building

```bash
# validate only
python shared/walkthrough/build.py --scenarios walkthroughs/*.json --root . --check-only

# inline into a course page at its <!-- WT:BUNDLE --> placeholder
python shared/walkthrough/build.py --scenarios walkthroughs/*.json --root . \
    --target output/M00-context-problem.html

# the tabbed quick-reference page
python shared/walkthrough/build.py --scenarios walkthroughs/*.json --root . \
    --standalone walkthrough/index.html --title "…" --back "../index.html"
```

The embedded build is **idempotent**: a rebuild replaces the block between
`<!-- WT:START -->` and `<!-- WT:END -->`, so the page needs the placeholder
only once. It refuses to build a page with no mount points, and refuses a mount
that names a scenario it wasn't given.

## Mounting

**Static module pages** (knowledge-graph) — put the mount at the *end* of the
section it belongs to, under the standing ritual:

```html
<h3>Walk it, step by step</h3>
<p>One sentence naming the lab and what to watch for. Never generic.</p>
<div data-wt="kg-147-files" data-wt-theme="dark"></div>
```

and `<!-- WT:BUNDLE -->` once, before `</body>`.

**Kit-format players** (ultimate-context-eng, context-eng-kit) — these swap
`innerHTML` on every module change, so the runtime re-mounts under a
`MutationObserver`; no player code changes. Add the mount with:

```bash
python shared/walkthrough/mount_player.py --html course/index.html \
    --module U07 --scenario uce-savings-void \
    --bridge "Step through the compression that wins on tokens and loses on truth."
```

which inserts one more `content` section immediately before that module's first
quiz — after the teaching, before the check — and verifies `MODS` still parses.

## Accessibility

Progress dots are buttons with `aria-label`s; the widget takes arrow-key
navigation; the terminal offers "show all" so nobody waits on an animation; and
`prefers-reduced-motion` disables every animation and starts the terminal fully
revealed.
