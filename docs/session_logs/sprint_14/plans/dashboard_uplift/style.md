# Style System — theta.md replication

> Visual language to replicate from theta.md. Applies across all dashboard-uplift
> pages. Cleaned 2026-07-16.

## Feel
Warm cream background, serif display type, monospace accents, muted earthy
tokens. Dense but calm information layout — generous whitespace, hairline
dividers, tabular numerals.

## Tokens (`src/styles.css`)
| Token | Value / role |
|---|---|
| `--background` | `#fcfbf8` (cream) |
| `--foreground` | near-black |
| `--muted` | taupe |
| `--border` | `#e8e3d6` (hairline) |
| `--accent` | olive / rust |
| `--positive` | green |
| `--negative` | red |
| `--warn` | amber |

## Typography
- **Serif** for headings + body — Fraunces or Source Serif 4.
- **Mono** for labels/numbers/badges — JetBrains Mono. Tabular numerals.
- Small-caps two-letter section badges (e.g. `MA` for Macro, `TR` for Track Record).
- Loaded via `<link>` in root layout.

## Components / conventions
- Two-letter mono badges beside nav labels + section headers.
- Thin hairline dividers, no heavy card shadows — border + subtle bg only.
- Range viz (bear/base/bull) = simple styled bar with markers, **no chart lib**.
- Status pills: BUY zone crossed / SELL zone crossed / Invalidation hit / Unexplained move.
- Filter chips row above dense sections (Price/valuation, Thesis/fundamentals,
  Catalyst/calendar, Sizing/portfolio, Supply chain, Regime/macro).

## Layout patterns (from theta pages)
- **Slim top nav / sidebar** (collapsible=icon): Dashboard, Portfolio, Calendar,
  Screening, Impact, Macro, Findings, Track Record — each with mono badge.
- **Header row:** page title · small book chip · "As of <date> ET" right-aligned.
- **Regime banner:** bordered, muted background, one-sentence macro read + F&G chip.
- **Decision cards:** left rail (mono code `A1` + ticker) · header (timing chip,
  action, % of book, source tag) · trigger sentence · bear/base/bull bar ·
  recommendation row + right-aligned timing · right status pill.
