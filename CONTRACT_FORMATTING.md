# Recommended Contract Formatting Standard

The parser turns a signed contract PDF into Asana sections and tasks by reading
**bullet glyphs and bold text**. The more consistent the contract templates are,
the more reliable (and portable) the automation. This is the highest-leverage
reliability investment available, because we control the DocuSign templates.

> Key principle: **glyphs and bold are portable; fonts are not.** The literal
> bullet character (`o`, `▪`) is stable across machines and PDF generators;
> font *names* (Calibri vs Wingdings vs Courier) vary. Standardize on glyphs and
> bold-for-structure, not on a specific font.

## The standard (one marker per level — never reuse)

| Level | Marker | Becomes in Asana | Rule |
|---|---|---|---|
| Deliverable group (optional) | Large **bold** heading (≥13pt), mixed-case | grouping | introduces a block of sections |
| **Section** | **Bold** heading line (or one consistent bullet, e.g. `●`) | Section | always bold; tasks never bold |
| **Task** | `o` (Courier-style) bullet | Task | one level of indent under its section |
| **Note / detail** | `▪` bullet | Task Notes | extra detail on the task above it |

### Do
- Keep **`o` for tasks** and **`▪` for notes** — both are already consistent across contracts.
- Make **sections bold** and **tasks/notes not bold** — bold is the structural signal.
- Use a consistent deliverables lead-in, e.g. *"… shall include all of the following:"*,
  and a clear transition into legal terms / payment afterward (so the parser knows
  where deliverables start and stop).
- Keep deliverables as **bulleted lists**.

### Don't
- ❌ **Reuse `•` for two different levels.** In past contracts `•` meant a *leaf perk*
  in one and a *section header* in another — the single biggest source of ambiguity.
  Pick one meaning (or drop `•` in favor of bold headings for sections).
- ❌ Put deliverables in **tables** — table-cell extraction is far less reliable than lists.
- ❌ Rely on a particular font to convey structure — use the glyph + bold instead.

## Why it matters

With a consistent template the parser can lean on **glyph + indentation** (stable,
portable) instead of font-name and bold-ratio heuristics (brittle). That means
fewer per-contract surprises, less manual cleanup in the preview, and a simpler,
more maintainable tool.

If a contract *can't* follow the standard, the tool still works — the editable
dry-run preview lets the operator fix any mis-parsed sections/tasks before anything
is written to Asana. The standard reduces how often that's needed; it isn't a hard
requirement.
