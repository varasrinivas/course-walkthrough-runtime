# shared — tooling used by more than one course

Small, self-contained build tooling that several courses in this workspace
depend on. Each course repo stays independently servable: whatever this
tooling generates is **committed into the course**, so a plain clone of a
course works with nothing else checked out. You only need this repo to
*rebuild*.

Courses expect it as a sibling checkout:

```
repo/
  shared/                     <- this repo
  knowledge-graph/
  ultimate-context-eng/
  context-eng-kit/
```

## What's here

| Path | What |
|---|---|
| [`walkthrough/`](walkthrough/) | The walkthrough runtime — interactive step-throughs embedded in course modules. See its [README](walkthrough/README.md) for the scenario schema and build commands. |
| [`domain/`](domain/) | The domain runtime — links a course's own vocabulary to its definitions, so a domain explained once in module zero stays reachable from module thirty. See its [README](domain/README.md) for the corpus schema and the gate. |

## domain, in one paragraph

Every one of these courses anchors on a domain — UCC lien filings, prior
authorization, a code knowledge graph — and explains it once, then assumes it.
The domain runtime turns the first use of each domain word in each view into a
chip that opens its definition, and puts the whole glossary behind one keypress.
Like the walkthrough it hydrates itself off a `MutationObserver` and builds its
own chrome, so a course integrates it by adding a single placeholder comment —
no player code changes, and nothing that touches what a module's source says.
Its build gate is the mirror image of the walkthrough's: where that one demands
*the evidence you cite must exist*, this one demands *the vocabulary you use
must be defined*.

## walkthrough, in one paragraph

A dependency-free port of the widget from `priorauth-sdd-course`: at the end of
a teaching section, an interactive re-enactment of a real session — what you
type, what the agent does, and the state before and after each step. It renders
the "screen" as styled HTML rather than shipping screenshots, which keeps it
searchable, restylable, weightless, and legal under the courses' "all CSS/JS
inline, no external assets" rules. Every scenario declares its provenance, and
a `measured` citation that does not resolve **fails the build** — the courses'
honesty rule enforced mechanically rather than promised in prose.

Used by:

- `knowledge-graph` — M00, M04, M09, Capstone 2
- `ultimate-context-eng` — U02, U05, U07, U10
- `context-eng-kit` — M01, M12, M18, M19
