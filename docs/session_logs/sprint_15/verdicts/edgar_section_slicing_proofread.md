# Verdict: EDGAR section slicing is trustworthy

> Sprint 15. Closes the Step-1 gate in
> [`tradingagents_business_analyst.md`](../plans/tradingagents_business_analyst.md):
> *"Manual proof-read of the first ~10 tickers before any batch run — non-negotiable."*
>
> Reviewed 2026-07-19 via `scripts/review_edgar_cache.py` (TradingAgents repo)
> against the cache at `~/.tradingagents/cache/edgar/`.

**Verdict: PASS.** Section slicing may be used for batch runs. Nine tickers
reviewed, all slices correct. The two flagged cases are correct behaviour and a
registrant-identity change, not slicing defects.

---

## What was checked

For each ticker, per section: the boundary pattern that matched at each end, how
many candidates were rejected, the char count against the sane band, and the
first 200 characters — which is where a table-of-contents mis-slice shows up
immediately.

| Ticker | Item 1 | Item 1A | Item 7 | Notes |
|---|---|---|---|---|
| RKLB | 59,825 | 116,628 | 53,426 | clean |
| AAPL | 16,150 | 68,256 | 18,472 | clean |
| NVDA | 48,854 | 116,049 | 35,505 | clean |
| PLD  | 42,009 | 53,568 | 66,072 | clean |
| COST | 20,944 | 42,574 | 27,469 | clean |
| F    | 75,187 | 93,700 | 161,669 | clean; largest in corpus |
| LLY  | 84,370 | 77,550 | 49,264 | clean |
| JPM  | 39,348 | 112,796 | — | Item 7 incorporated by reference (see below) |
| XOM  | 6,746 | 35,960 | — | Item 7 incorporated by reference; CIK pinned (see below) |

No slice began inside a table of contents. Every accepted start matched a real
section header followed by real prose, and every end matched the next item
header.

## The two flags

### JPM — Item 7 incorporated by reference (correct behaviour)

JPMorgan's Item 7 body is a cross-reference: *"Management's discussion and
analysis … appears on pages 46–160."* The slicer detected this, rejected both
candidate slices (398 and 101 chars) as below `min_chars`, and wrote **no
`item7.md`** rather than a stub.

This is exactly the designed outcome. Verified downstream: `extract_log`
records `status: incorporated_by_reference`, the excerpt pack tells the model
the section is unavailable, and `BusinessProfile.sections_unavailable` carries
it into the rendered report. A reader can tell *"the filing did not say"* from
*"we could not read it"* — which is the distinction the whole schema exists to
protect. XOM behaves the same way.

Roughly a fifth of filers do this. It is a normal state, not an error.

### XOM — successor-registrant CIK, not a slicing problem

XOM's cached slices are correct (the short 6,746-char Item 1 is real — Exxon
writes a terse business section, and the slice runs from `PART I ITEM 1.
BUSINESS` to the standard SEC-website boilerplate that closes the item).

The failure was at *fetch* time: ExxonMobil reorganised into a holding company
(Form 8-K12B), so SEC's ticker table now resolves XOM to successor CIK
**2115436**, which has no filing history. The 10-K remains under predecessor CIK
**34088**, and EDGAR publishes no predecessor link.

Resolved by pinning it in TradingAgents `.env`:

```
TRADINGAGENTS_SEC_CIK_OVERRIDES={"XOM": 34088}
```

Verified: XOM now resolves to 34088 and fetches accession
`0000034088-26-000045`. Note this pin is machine-local — a fresh clone will hit
the same failure until the variable is set.

### ARM — non-10-K filer, fails loudly as specified

ARM Holdings plc is a UK issuer and files 20-F, so it is out of scope for v1.
The plan requires it fail loudly rather than silently produce an empty profile.
Confirmed:

```
NoMarketDataError: No market data for 'ARM': no 10-K under CIK 1973239
(ARM HOLDINGS PLC /UK). ADRs file 20-F, some Canadian issuers 40-F.
Recent forms seen: 144, 20-F, 3, 4, 424B4, 6-K, 8-A12B, CERT, ...
```

The message names the CIK, the registrant, and the forms actually present. The
`business_analyst` node catches this and emits an explicit "no 10-K narrative
available" report rather than a null profile.

## Known limitation worth recording

`fetch_10k()` resolves ticker → CIK → filing over the network *before* reading
the cache, so a cached filing becomes unreachable when upstream identity
changes — which is precisely how XOM broke despite having valid cached data.
Not fixed here; a cache-first lookup keyed on ticker would avoid it, at the cost
of not noticing a genuinely newer filing.
