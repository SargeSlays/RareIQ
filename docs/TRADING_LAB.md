# RareIQ Paper-First Trading Lab

This subsystem is a controlled research experiment, not a promise of income and
not a live-trading product. Turning $100 into $1,000,000 means multiplying the
account 10,000 times. Even a sustained 20% annual return would take about 50.5
years without additional contributions. The family-protection objective and a
"fast as possible" risk objective point in opposite directions.

The phase-one success condition is narrower: determine whether a frozen idea has
repeatable after-cost evidence while preventing unauthorized or oversized orders.
Do not fund a live account for this milestone.

## What is implemented

- A frozen long-only SPY 200-day moving-average baseline.
- An optional deterministic walk-forward logistic research candidate. It is an
  inspectable numerical model, not an LLM, and it never bypasses risk checks.
- Next-session backtesting with fractional shares, slippage, fees, a stress-cost
  scenario, cash and matched-exposure buy-and-hold benchmarks, and no look-ahead
  labels.
- Direct Alpaca historical data and **paper-only** order integration. The trading
  hostname is a source-code constant; no live hostname or live mode exists.
- Deterministic client order IDs, pre-submit order lookup, uncertain-submission
  reconciliation against an exact persisted payload, one routine entry order per
  session, and an append-only local decision journal. Sell orders explicitly use
  `sell_to_close`; validated filled/canceled emergency exits with a confirmed
  residual position advance to a new deterministic retry generation.
- A manual kill switch that latches locally before requesting cancellation of all
  paper orders, verifies the immutable broker-account binding, every cancellation
  response, and that no open order remains. Its sentinel and account binding are
  independent of the ordinary config/state parsers, so corrupted files cannot
  silently disable cancellation. The local halt stays latched even if broker
  verification fails. It makes an immediate cancellation attempt before waiting
  for the serialized execution lock, then repeats cancellation under that lock.

Hard configuration ceilings prevent more than $250 of managed paper equity, more
than 35% exposure, more than 10% of equity in a new buy order, leverage, shorts,
options, crypto, extended-hours orders, or unapproved symbols. Defaults are much
tighter: a $125 review ceiling, a 25% exposure target with a two-percentage-point
rebalance band, a 10% cash buffer, a 1% daily portfolio-loss halt, and an 8%
high-water drawdown halt. The immutable phase-one exposure ceiling is 35%, though
price gaps can cross a limit before the next safe exit. A latched halt takes a
history-independent SPY exit path, so a historical-data or model outage cannot by
itself block a fresh-quote emergency sell. Submission also
requires a quote no more than five seconds old and a quoted spread no wider than
20 basis points. Routine entries and rebalances are limited to 9:30 a.m. through
just before 9:35 a.m.
US Eastern time, derived from Alpaca's session clock; a risk-reducing sell may run
later during regular hours. A routine sell is blocked on the same session as a
buy, while a latched emergency halt may override that block. Market gaps can still
exceed any intended loss limit.

## Why Alpaca paper trading

Alpaca currently supports free paper accounts, an arbitrary paper balance, and
fractional US-equity orders from $1. The free plan is IEX-only. Alpaca explicitly
warns that paper fills omit market impact, latency slippage, queue position,
regulatory fees, dividends, and other live effects, so paper profit is not proof
of an edge. The free IEX quote is one-venue BBO, while Alpaca says its paper fills
are matched against consolidated NBBO; this mismatch is another explicit limit:

- <https://docs.alpaca.markets/us/docs/paper-trading>
- <https://docs.alpaca.markets/us/docs/fractional-trading>
- <https://docs.alpaca.markets/us/docs/about-market-data-api>

FINRA's new intraday-margin framework became effective June 4, 2026, with a broker
transition period through October 20, 2027. RareIQ avoids margin and routine
same-day round trips regardless of a broker's transition status; an emergency
risk exit may close a same-day paper position:

- <https://syndication.finra.org/content/understanding-new-intraday-margin-requirements>
- <https://www.investor.gov/introduction-investing/investing-basics/glossary/day-trading>

## Local setup

Create an Alpaca **paper** account funded with exactly $100. Never place credentials in
JSON or commit them. Copy the local configuration and validate it:

```powershell
Copy-Item trading_config.example.json trading_config.json
.venv\Scripts\python.exe -m rareiq.trading validate-config --config trading_config.json
```

Set paper credentials only for the current PowerShell session:

```powershell
$env:APCA_API_KEY_ID = "your-paper-key"
$env:APCA_API_SECRET_KEY = "your-paper-secret"
```

Download adjusted daily bars and their hash-bound provenance sidecar, then run
both base- and stress-cost simulations:

```powershell
.venv\Scripts\python.exe -m rareiq.trading download --config trading_config.json --start 2016-01-01 --end 2026-08-27 --output runtime/trading/SPY.csv
.venv\Scripts\python.exe -m rareiq.trading backtest --config trading_config.json --csv runtime/trading/SPY.csv --report runtime/trading/backtest.json
```

The backtest accepts only the registered Alpaca schema-v1 sidecar: matching SPY,
IEX, `1Day`, `adjustment=all`, exact hash/count/range/first/last timestamps, and
timezone-aware generation/request timestamps. Bars must be chronological New
York-midnight weekday observations with at least 94% weekday coverage. This
includes a seven-calendar-day maximum internal/trailing gap for paper execution.
These checks catch stale, sparse, or intraday inputs, but are not an exact XNYS holiday-calendar
audit, so the report remains preliminary. The report embeds the normalized config
and an implementation hash. Alpaca history begins in 2016, so this command cannot
satisfy the 15-year promotion gate by itself.

To research the machine-learning candidate, change only `strategy` in the ignored
local configuration to `walk_forward_logistic`, record that choice before viewing
the output, and write to a separate report. Paper logistic mode requires
`retrain_every_bars=1`, so its backtest must use that identical value. Do not tune
parameters against the same final holdout until it passes.

After historical review, change `mode` to `paper`. A plan submits no broker order,
but it does persist the immutable local account binding, risk state, and audit log:

```powershell
.venv\Scripts\python.exe -m rareiq.trading paper --config trading_config.json
```

A simulated routine order requires the first five minutes of the regular session
(9:30 a.m. through just before 9:35 a.m. US Eastern, including DST), every risk check, an exact
acknowledgement, and the explicit submission flag. Risk-reducing sells may execute
later during regular hours:

```powershell
$env:RAREIQ_PAPER_ORDER_ACK = "PAPER_ONLY_I_ACCEPT_SIMULATED_ORDERS"
.venv\Scripts\python.exe -m rareiq.trading paper --config trading_config.json --submit-paper-order
```

The emergency command is:

```powershell
.venv\Scripts\python.exe -m rareiq.trading kill-switch --config trading_config.json
```

The emergency path always uses the canonical runtime directory and can cancel the
bound paper account even if the supplied config or ordinary state JSON is missing
or corrupt. It cancels orders; it does **not** silently liquidate holdings. If a
position remains, the command exits with an error and records that follow-up is
still required. A healthy halted state can use the history-independent risk-exit
path; corrupt state requires manual broker action.

Runtime state, reports, the immutable account binding, kill sentinel, and the
append-only journal live under `runtime/trading` under the project root and are
ignored by Git. Every mode is pinned to that one canonical directory. The state is
bound to one broker account ID, an exact initial $100 cash/equity snapshot, and a
configuration hash. A halt is intentionally sticky and requires a code/state
review before manual reset.

## Promotion gates

Do not consider live code until all of these are true:

1. At least 15 years of correctly adjusted data, walk-forward evaluation, a
   frozen final three-year holdout, base and stress costs, and at least 30
   completed round trips (not merely order fills).
2. Positive out-of-sample net results in both cost cases, no parameter retuning on
   the holdout, and drawdown no worse than the pre-registered limit and benchmark.
3. At least 60 market days in an exact-$100 paper account with zero duplicates,
   unauthorized symbols, reconciliation mismatches, or risk bypasses.
4. Failure drills for stale/missing data, HTTP 429/5xx, timeouts after acceptance,
   restarts, partial fills, open-order reconciliation, and the kill switch.
5. A separate 30-day shadow run using live observations but submitting no orders.

Paper returns are logged but are not a graduation criterion. Any eventual micro-
live phase needs a separate implementation and review; it is deliberately absent
from this codebase.

The current MVP verifies intended order identity and uncertain submissions, but it
does not yet maintain a complete expected-cash/position fill ledger. Consequently,
the reconciliation requirement in Gate 3 is intentionally **not passable yet**;
partial-fill and manual-activity reconciliation must be implemented and tested
before any promotion discussion.

Alpaca's stock history currently starts in 2016, so its feed alone cannot satisfy
the 15-year gate or cover 2008. The included downloader is sufficient for software
and preliminary research tests only. Promotion requires a separately licensed,
point-in-time historical source and a new validated provider adapter.
