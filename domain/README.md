# domain runtime

A course anchored on a domain explains that domain once — usually in module
zero — and then assumes it for thirty more. A reader who starts in the middle,
or who forgets what a `UCC-3` or an `OKF` or an `arm` is by module fourteen, has
nowhere to look.

This makes the first use of each domain word **in each view** a chip that opens
its definition, and puts the whole glossary one keypress away from anywhere.

Used by `context-eng-kit`, `ultimate-context-eng`, `knowledge-graph`.

## Why it needs no player changes

Like the walkthrough runtime, it hydrates itself: a `MutationObserver` on
`document.body` re-links after a module swap, so a player that replaces
`#mvBody.innerHTML` is handled without knowing this exists. It also builds its
own chrome — panel, popover, opener — into `document.body`, adopting the host's
top bar when `config.chrome.topbar` matches one, so **no course markup is
edited at all**. One `<!-- DG:BUNDLE -->` placeholder before `</body>` is the
entire integration.

That matters beyond convenience: these courses validate their *authored* markup
against closed class vocabularies (`scripts/check-module.js` rules 23/24 in
context-eng-kit). Linking at runtime, over the rendered DOM, means nothing here
can put a class into a module's source.

## Files

| File | What |
|---|---|
| `runtime.js` | index, linker, popover, panel, observer (~20 kB, no dependencies) |
| `runtime.css` | every rule `dg-`prefixed; themes off the host's own variables |
| `build.py` | validate, run the gate, inline the bundle |
| `harvest.py` | seed a corpus from a course's existing hand-written tooltips |

## The corpus

One JSON file per course.

```jsonc
{
  "title": "UCC Glossary",
  "subtitle": "Every domain word this course uses.",

  "config": {
    "scope":  ["#mvBody", "main.content", "body"],   // first match wins
    "skip":   [".ue-fv", ".quiz-option"],            // APPENDED to the base list
    "chrome": { "topbar": "#themeToggle" },          // adopt this button's styling
    "shortcut": "g"
  },

  "watchlist": [
    { "word": "arm",     "term": "Arm" },
    { "word": "perfect", "skip": "ordinary English — 'a perfectly worded prompt'" }
  ],

  "glossary": [
    { "term": "Open Knowledge Format",
      "short": "one sentence — what it is",
      "long":  "optional — why it matters, or what goes wrong",
      "match": ["OKF"],          // extra surface forms; plain plurals are automatic
      "cs":    true,             // match only this casing (acronyms)
      "see":   ["Provenance"],   // cross-refs, shown in the popover
      "source": "docs/okf-spec.md"   // optional, and gated
    }
  ]
}
```

`match` exists for inflections that do not share the headword's prefix
(`perfected` → `Perfection`) and for acronyms whose expansion is the headword
(`OKF` → `Open Knowledge Format`). Plain plurals need no entry.

`cs` pins an entry to its declared casing. Use it for acronyms and for tags like
`EXTRACTED` / `INFERRED`, so they never match ordinary prose.

## The gate

The walkthrough runtime's gate asks *the evidence you cite must exist.* This one
asks its mirror image: **the vocabulary you use must be defined.**

**Hard failure**, and only this: a `watchlist` word that appears in the course's
prose must resolve to a glossary term, or carry a written reason for not needing
one.

```
BUILD FAILED: watchlist word 'arm' appears 40 times in the course prose
      but resolves to no glossary term.
      Add a term to docs/domain-corpus.json, or opt it out with
        {"word": "arm", "skip": "<why this word needs no definition here>"}
```

The opt-out is deliberately annoying: you have to write the sentence. That is
strictly better than absence, which is indistinguishable from an oversight —
`perfect` is the standing example, a word `context-eng-kit` must never link to
*Perfection* because it uses it fifteen times in the ordinary sense.

**Advisory, never fails:** `--report` ranks candidate jargon that is on neither
list, formatted as a paste-ready `watchlist` stanza. Discovery is heuristic, and
a heuristic must not gate a build — that is how gates get switched off.

Also reported, never fatal: glossary terms the prose never uses. A definition
the reader will never meet is usually a renamed term.

## Building

```bash
# gate only
python ../shared/domain/build.py --corpus docs/domain-corpus.json --root . \
    --prose course/index.html --prose-mode mods --check-only

# what am I still assuming?
python ../shared/domain/build.py --corpus docs/domain-corpus.json --root . \
    --prose course/index.html --prose-mode mods --check-only --report

# build
python ../shared/domain/build.py --corpus docs/domain-corpus.json --root . \
    --target course/index.html --prose course/index.html --prose-mode mods
```

`--prose-mode mods` reads the strings inside `const MODS = [ … ];` — for a
kit-format player that is what a reader actually reads, and scanning the raw
file instead would fold in the runtime, the walkthrough bundle and every CSS
rule. `--prose-mode html` strips tags, after excising the generated regions,
`<svg>`, `<pre>` and `<code>`.

Deploy staging trees are excluded from every scan. `ultimate-context-eng`'s
`scripts/dist/courses/` holds complete copies of **four other courses**,
knowledge-graph among them, so a naive scan reports another course's vocabulary
as this one's.

Generated output is committed into each course, so a plain clone serves without
this repo checked out. You only need it to rebuild — and you must rebuild after
anything that regenerates the page, exactly as with the walkthrough bundle.

## Harvesting an existing convention

Some courses already mandate a definition on first use and carry the result
inline — knowledge-graph's `.term-tooltip`/`.tooltip-content` spans. Those are a
glossary that was never collected: the same word is re-defined by hand in each
module that mentions it, and the reader in the module that *didn't* define it is
still stuck.

```bash
python ../shared/domain/harvest.py --html "output/*.html" --out domain/corpus.draft.json
```

It writes a draft and **reports conflicts rather than resolving them**, because
two hand-written definitions of one word may disagree and choosing between them
is editorial. Run against knowledge-graph it found 44 terms in 52 tooltips — and
six words defined two different ways: `context window`, `MCP`, `token`,
`compacted`, `language server`, `attested computation`.

The runtime never touches an existing `.term-tooltip`; both are in the base skip
list. A course can retire its hand-written ones later, or keep both.

## What is never linked

```
code, pre, kbd, samp, var, tt          the reader is meant to read the bytes
a, button, select, textarea, label     a chip inside one eats its clicks
svg, math, canvas                      another namespace
h1–h6, script, style, [contenteditable]
[data-wt], .wt                         the walkthrough widget owns its subtree
.term-tooltip, .tooltip-content        a hand-authored definition wins
.dg-ui, .dg-chip, [data-dg-skip]
```

`svg` is in that list because omitting it is not hypothetical: it put **27 of
160 chips inside diagram `<text>` nodes** in context-eng-kit, where an HTML
`<button>` does not render without a `foreignObject` — *and*, being the module's
first match, each one consumed its term so the real first prose occurrence went
unlinked. Assert against the skip list itself in tests, never a hand-picked
subset; that is precisely what let it ship.

## Three things in the runtime that look optional and are not

**The sentinel is a child, not an attribute.** A kit player does
`mvBody.innerHTML = html`: the scope element survives, only its children are
replaced. An attribute marking "already linked" would outlive the swap and be
true forever. A child is erased by it — which is exactly the signal we want.

**`used` is read from the DOM, not held in a variable.** Chips already placed
sit inside `.dg-chip`, which the walker skips. A fresh in-memory set would
therefore believe every term unspent, miss the first occurrence because it is
hidden inside a chip, and link the *second* — then the third on the next pass.
Deriving `used` from `.dg-chip[data-dg-term]` makes a repeat pass a genuine
no-op, and makes "first occurrence per module" and "reset on module change" fall
out for free.

**The mutation-record filter is required, not defensive.** `walkthrough/runtime.js`
types a character every 16 ms while a scenario plays. Without dropping records
that originate inside `.wt`, `[data-wt]` or a course's own animation stages,
every running walkthrough would schedule a full tree walk every 60 ms for its
whole duration.

One more, host-specific: the `keydown` listener is **capture phase**, because
`ultimate-context-eng` binds `Escape` to "return to landing". A bubble-phase
listener would close the panel *and* throw the reader off the module.
