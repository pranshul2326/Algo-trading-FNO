# Matheran

Approval-gated intraday trading engine for NSE/BSE equity and index options, with a
browser console for everything: credentials, strategy tuning, the options scan table,
approvals, and the trade journal.

The engine never opens a position on its own. It watches, and when every condition
lines up it raises an approval card. You press **Approve & buy**. After the exit it
re-arms and asks again.

---

## Quick start

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp config.example.yaml config.yaml          # optional; sane defaults apply either way
.venv/bin/python run.py serve
```

Open <http://127.0.0.1:8787>.

1. **Setup** tab → *Generate console API key*. It is written to `.env` (mode `0600`) and
   applied immediately; the browser tab keeps it for you.
2. Fill in your broker credentials in the same tab, press **Save credentials**, then
   **Test connection**, then **Apply to engine**.
3. Leave mode on **paper** until you trust it. Paper uses real market data and simulates
   fills; nothing reaches the exchange.

Without any broker credentials the service still runs on a synthetic feed, so you can
click through the whole UI before connecting an account. Everything is labelled
`data_source: synthetic` in that state.

### CLI

```bash
.venv/bin/python run.py selfcheck                    # validate the indicator maths
.venv/bin/python run.py doctor                       # config + broker connectivity
.venv/bin/python run.py chain --underlying NIFTY     # print the scan table
.venv/bin/python run.py scan --universe nifty50   # live BUY/SELL scanner
.venv/bin/python run.py serve --port 8787            # API + console
```

---

## The strategy

Each stock watch trades **LONG** (buy, then sell), **SHORT** (sell, then buy back) or
**BOTH** (whichever side lines up, one position at a time). A short is the exact mirror
image of a long. Signals are evaluated **only on closed candles** of the chosen
timeframe, so a condition cannot appear and vanish inside the same bar.

**Entry** — all of:

| # | Long (BUY) | Short (SELL) |
|---|---|---|
| 0 | Current price above session VWAP | below session VWAP |
| 1 | RSI(21) above EMA(RSI(21), 21) | RSI(21) below it |
| 2 | Price above Supertrend(21, 0.618) | price below it |
| 3 | ADX(14) above 20 — options only by default | same (ADX has no direction) |

A BOTH watch checks both columns. They cannot both hold at once, because price cannot be
above and below VWAP together, so at most one approval is ever raised. The approval card
says BUY or SELL in so many words.

**Exit** — whichever comes first:

| Trigger | Long | Short | Checked on |
|---|---|---|---|
| Exit conditions (below) | as written | the mirror image | per row: candle close or live price |
| Stop loss: 3% of capital deployed | 3% below entry | 3% above entry | live price, between candles |
| Target %, if you set one | above entry | below entry | live price, between candles |
| Trailing profit, if you set one | stop follows the best price once in profit | mirror image | live price, between candles |
| Square-off at 15:15 IST (intraday only) | | | clock |

**Exit mode** picks which of those apply: *SL / target + exit conditions* (the default),
*SL / target only*, or *exit conditions only*. The last one has no stop at all, so a trade
runs until a condition fires, the square-off, or you exit it; it is refused while the
Strategy tab has no exit conditions. Set the default on the Strategy tab, and override it
per watch, per basket, or per order in the order dialog and the chart ticket.

**Product** is *Intraday* (squared off at 15:15, no new entries after 15:00) or
*Delivery* (CNC for shares, NRML for futures and options): carried overnight, never
squared off, and allowed to enter until the close. A carried position keeps its stop: the
day order at the broker lapses at the close and is placed again at the next open, and on a
restart the position is found in the broker's positions or holdings. Shares cannot be sold
short as delivery, so a SHORT or BOTH watch on a stock must be intraday.

**Trailing profit** (Strategy tab): once a trade is *N*% in profit, the stop follows the
best price since entry at a distance in % or points and never moves back. Before that the
normal stop applies. A stop that has trailed is booked as `trailing_profit`.

**Timeframes**: 1, 3, 5, 9, 15 and 30 minutes, 1 and 2 hours, 1 day, 1 week, 1 month, for
watches, the options scan, the Strategy tab and every chart. Intraday bars are anchored at
09:15 (a 2-hour bar spans 09:15–11:15, and the last of the day is the 15:15–15:30
remainder); a day bar is one session, a week Monday to Friday, a month the calendar month.
From an hour up, earlier sessions come from the data provider's history service.

### Exit conditions

The Strategy tab builds the indicator exits as rows, one condition per row: an
indicator with its parameters in text boxes, a comparison (crosses below / above,
below / above, at or below / above), and a second indicator or a number. Rows are
joined with AND / OR; AND binds tighter than OR, as in Pine Script, so
`A AND B OR C` means `(A AND B) OR C`. The tab reads the rows back in words for both
directions before you save.

Indicators: Close, Open, High, Low, VWAP, EMA, SMA, Supertrend, RSI, EMA of RSI, ADX,
+DI, −DI, ATR, or a plain number.

Each row is checked either

- **on candle close** — on the last closed candle of the watch's timeframe, and only on
  candles that closed *after* the position was opened, so a condition that already held
  when you bought cannot sell you straight back out; or
- **live price** — on the candle still forming, its close taken from the live price, so
  it can fire between closes.

The default rows are the original two (RSI(21) below EMA(RSI(21), 9), or close below
Supertrend(21, 0.618), both on candle close); decision for decision they exit exactly as
before. A short uses the mirror image: above ↔ below, crosses above ↔ crosses below, RSI
levels reflected around 50 (70 ↔ 30), +DI and −DI swapped; ADX and ATR carry no
direction and stay as written. The rows live in `config.yaml` as `strategy.exit_rules`;
`null` means the default two, `[]` means no indicator exits at all.

```yaml
strategy:
  exit_rules:
    - left:  {ind: rsi, period: 21}
      op:    crosses_below
      right: {ind: rsi_ema, rsi: 21, period: 9}
      on:    close
    - join:  OR
      left:  {ind: close}
      op:    below
      right: {ind: supertrend, period: 21, factor: 0.618}
      on:    close
```

Entries wait until there is enough history for the exit conditions as well, so a
position is never opened whose exits cannot be evaluated yet.

### The 3% stop

Capital deployed on a leg is `entry price × quantity`, so losing 3% of it is a 3%
adverse price move:

```
stop price = entry price × 0.97     (snapped to the instrument tick size)
```

For 40 shares at ₹250 → ₹10,000 deployed, stop at ₹242.50, risk ₹300 = 3.000%.

Two layers enforce it. A resting `STOP_LOSS_MARKET` order is placed at the broker so the
stop survives this process dying, and the engine independently watches the live price. If
the broker rejects the resting order, the watch says so and the engine-side stop still
fires.

### Indicator conventions

Written to match TradingView (Pine v5), because that is probably what you are eyeballing:

- `ta.rma` / `ta.ema` are seeded with the SMA of the first `period` values, not the first value
- `ta.atr` uses RMA, and true range on the first bar is `high − low`
- Supertrend follows Pine's band-locking and direction-flip logic exactly; `direction == -1`
  (uptrend) is the same test as "price above supertrend"
- VWAP uses the typical price `(H+L+C)/3`, cumulative, reset every session
- Feeding RSI into an EMA skips the NaN prefix, as Pine does with `na` series

`run.py selfcheck` proves each of these against an independently written reference
implementation plus invariants, along with the day, week and month bars, the zero-lag EMA,
Heikin Ashi and Renko. 80 checks.

---

## The console

| Tab | What you do there |
|---|---|
| **Setup** | Credentials, broker choice, paper/live, connection test, apply to engine |
| **Trade** | Add stock watches (LONG / SHORT / BOTH, intraday or delivery, an exit mode), approve or reject signals, see live indicator values and a **Ready** column (every entry condition met, each one in the tooltip), manual Buy / Sell at market or limit, exit positions |
| **Options** | ATM + N OTM scan table, one-click watch on any contract, Buy at market or limit |
| **Baskets** | Build buy + sell combinations, execute them at market or as limit orders, exit them as one, live P&L per leg, chart the combined premium |
| **Strategy** | Every strategy, risk and session parameter: exit mode, default product, trailing profit, and the exit conditions row by row, saved to `config.yaml` |
| **Journal** | Trade log with direction, realised P&L and what exactly closed each trade, and open positions |
| **Charts ↗** | `/charts` — multi-pane live candlestick grid, with a Trade button on every pane |
| **Option chain ↗** | `/chain` — calls, strikes and puts on one page, with OI, OI change and 5-minute buildup |
| **Basket combo ↗** | `/combo` — a basket's underlying, combined premium, calls and puts on one 2 × 2 screen |

The header always shows mode (with a loud red pill in live), broker and data source,
whether the market is open, whether a key is required, and a **Halt** button.
Halt stops new signals and optionally squares off everything.

### Options scan

For the chosen underlying it finds the nearest expiry, locates the ATM strike from index
spot (or the near-month future), and tabulates the ATM strike plus *N* OTM strikes on each
side — calls above, puts below:

```
CONTRACT                   TYPE   STRIKE  MONEY      LTP     VWAP  >VWAP     RSI  EMA(RSI)    EMA21   SUPERT    ADX  READY
NIFTY 23250 PE               PE    23250  OTM+2   200.61   196.74    yes   68.56     62.35   199.79   200.50   32.9  READY
```

Rows meeting every entry condition are flagged `READY` and highlighted. The
`Blocking condition` column tells you exactly which test failed for the others. (That is
the `run.py chain` output; the console's Options tab shows the same columns without
`MONEY`.) The Trade tab's watches carry the same **Ready** column.

### Option chain

`/chain` is the classic one-page chain: calls on the left, strikes in the middle, puts on
the right, for any index or F&O stock. Type the underlying and pick the expiry, how many
strikes each side of the ATM to show, and the buildup window. The page refreshes itself
every 60 s. Per contract:

| Column | Meaning |
|---|---|
| LTP (chg %) | latest price, and change against the previous session's close |
| OI | open interest, with a bar relative to the largest shown |
| OI chg | open interest against the previous session's close |
| OI chg (win) | open interest change over the buildup window (default 5 min) |
| Buildup | price move against OI move over that window: **Long Buildup** (price ↑ OI ↑), **Short Buildup** (↓ ↑), **Short Covering** (↑ ↓), **Long Unwinding** (↓ ↓). The day's reading is in the tooltip |

In-the-money cells are shaded, the spot price is marked between strikes, and the header
shows PCR and total call/put OI. Every contract has a **Chart** button, which opens it
beside its underlying, and **B** / **S** buttons that add it to the basket builder pinned
to the bottom of the page. The builder sends the basket at market or as limit orders (a
price per leg, prefilled with the LTP), intraday or delivery (NRML).

Everything comes from the free Upstox 1-minute candles, with no token needed. The first
load of a 17-strike chain makes about 70 requests and takes around 7 s. After that it
answers from the 45 s candle cache. Refreshing every 60 s uses about half of Upstox's
2,000-requests-per-30-minutes allowance, so pick fewer strikes or 120 s if you also
keep many charts open.

---

## Scanner

The **Scanner** tab (and `run.py scan`) checks a universe of NSE/BSE stocks and MCX
commodities against a BUY list of conditions and its mirror-image SELL list, on live data.
It is read-only: it never places an order, creates an approval or adds a watch by itself.
Each result row offers Chart and Watch (NSE/BSE equities; MCX gets Chart only).

Default BUY conditions, all joined with AND (saved under `scanner:` in `config.yaml`):

| # | Timeframe | Condition |
|---|---|---|
| 1 | 1W | RSI(14) at or above 50 |
| 2 | 1D | price at or above EMA(200) |
| 3 | 1D | price above Supertrend(21, 0.618) |
| 4 | 2h | price above Supertrend(21, 0.618) |
| 5 | 5m | price above Supertrend(21, 0.618) |
| 6 | 15m | price above VWAP |
| 7 | 15m | RSI(21) at or above EMA(RSI(21), 14) |

SELL mirrors BUY with the exit-condition rules (above ↔ below, RSI levels reflected around
50) and is read back in words. Unlink it to edit SELL on its own. Rows are edited with the
Strategy tab's row builder plus a timeframe per row (1m 3m 5m 9m 15m 30m 1h 2h 1D 1W 1M).
Each row is evaluated on the **live** forming candle by default, its close at the live price
(as TradingView draws it), or on the **last closed** candle. A row without enough history is
n/a and counts as not met.

**Universes.** Nifty 50, Nifty Next 50, Nifty 200, Nifty 500, Midcap 150/100 and Smallcap
250/100 come from NSE's archive CSVs (niftyindices.com as the fallback), fetched once per IST
day into `cache/universes/`. Offline, the cached copy of any age is used, then the dated
snapshot in `matheran/universe_snapshot/` (refresh it by copying the CSVs from
`cache/universes/`). **F&O** is every stock with NSE stock futures in the Upstox master,
scanned on its cash price. **MCX** is the near-month future of each commodity. Custom
symbols take an exchange prefix (`RELIANCE`, `BSE:TCS`, `MCX:GOLD`, up to 200). Several
selections are merged without duplicates.

**Request budget.** Upstox allows about 2,000 requests per 30 minutes per IP. The scanner
takes at most `max_requests_per_30min` (1,500) of them at `requests_per_second` (6), counted
across the server and the CLI, and waits rather than exceed them. A symbol costs one request
for today's bars plus one per history window. History is cached on disk per IST day (a
window without the previous session, fetched before 09:00, is refetched after 30 minutes),
so a repeat scan costs about one request per symbol, and none on a weekend or before the
open. Evaluation `auto` checks every condition when the estimate fits 600 requests, else
`lazy` stops at a symbol's first failed condition. Expected costs: Nifty 50 ≈ 200
requests first scan, ≈ 50 repeat; Nifty 500 lazy ≈ 1,100–1,400 first, ≈ 500 repeat. A forced
`complete` Nifty 500 scan needs about 2,000 and so takes about 30 minutes under the 1,500 cap.
The estimate, progress, ETA and a Cancel are on screen. One scan runs at a time per machine.

**Auto-rescan** (off by default) repeats the scan every 2–60 minutes while the console is
open. Loading the page never starts it: it is armed by pressing Run, refused when the repeat
cost would exceed the scanner cap, and stopped by Off, Cancel or closing the page.

```bash
.venv/bin/python run.py scan --universe nifty50 --side both --values
.venv/bin/python run.py scan --universe nifty500 --universe mcx
.venv/bin/python run.py scan --symbols NSE:RELIANCE,BSE:TCS,MCX:GOLD --all --json -
```

Limitations:

- **MCX history:** a near-month contract has only its own short history (no continuous series
  without Upstox Plus), so `[1D] EMA(200)` is n/a for every contract and no MCX commodity
  matches the default rows.
- After 15:30 the daily forming bar closes at the last traded price, not the official close.
  Exchange holidays are not modelled.
- The scanner counts its own requests across processes sharing `cache/scan/`, but not the
  engine and chart requests of another process or other apps on the same IP.
- BSE watches on Upstox data still get no candles (unchanged engine); the scanner and charts
  use a data-only BSE path.
- Live quotes need a valid Upstox token (or Dhan as the NSE data broker). With an expired
  token the scan uses candle closes and says so. Any other data path (Stoxkart today) is
  scanned on candle closes, and Stoxkart without its own data broker cannot be scanned.
- REITs in the index lists are scanned but cannot be charted or watched; a renamed index
  member is scanned under its current symbol (matched by ISIN), with a note.
- The cache in a cloud-synced folder: see below.

### Where the cache lives

`cache/` (the scanner's history windows, `cache/scan/`, plus the instrument masters) sits
next to `run.py`. If the project folder is synced by OneDrive, iCloud Drive or Dropbox,
exclude `cache/` from sync, or run Matheran from a non-synced directory. A first scan of the
day writes about 1,000–1,500 small files there, and a running scan refreshes
`cache/scan/.running` every 2 s and `cache/scan/ledger.json` every 10 s. The app logs a
notice when it detects this.

---

## Charts

`/charts` is a split-screen grid of live candlestick charts built on
[TradingView Lightweight Charts](https://tradingview.github.io/lightweight-charts/)
v5.2.1 (Apache-2.0). Plain HTML and plain CSS, no framework and no build step. The
library is vendored in `matheran/static/`, so charts work offline and nothing is
fetched from a CDN.

- **Number of charts**: 1, 2, 4, 6 or 8. One plain CSS rule per count —
  1 = full screen, 2 = side by side, 4 = 2×2, 6 = 3×2, 8 = 4×2. Media queries collapse
  to fewer columns on narrow screens and to a single column on mobile.
- **Every pane is independent**: its own symbol, its own timeframe
  (1m / 3m / 5m / 9m / 15m / 30m / 1h / 2h / 1D / 1W / 1M) and its own chart type:
  **Candles**, **Heikin Ashi** (indicators stay on the real prices, and the price shown is
  the real last trade) or **Renko** (bricks of a box size you type, or ATR(14) of the
  timeframe when left blank; indicators are computed on the bricks).
- **Countdown**: the time left in the candle now forming sits beside the last price on the
  price axis, as on TradingView, and in the pane bar; it reads "candle closed" outside the
  session.
- **Drawing tools** in the header: trend line, ray, horizontal and vertical line, box,
  Fibonacci retracement and text. Click two points or drag; with the pointer, click a
  drawing to select it, drag it or its ends to move it, recolour it, and Delete removes it.
  Drawings belong to the symbol, so they show on every pane of it at any timeframe, and are
  kept in this browser.
- **Extra indicators** with their own parameters, edited in the picker: **ZEMA**, the
  zero-lag EMA (EMA of price + (price − price[lag]), lag = (period − 1) / 2), twice, at 50
  and 200 by default; and a **two-timeframe Supertrend**, two lines each with its own
  timeframe (the chart's, or any other), ATR period and factor. A higher timeframe's line
  shows on each chart bar the value it had at that moment, and settles on the higher
  bar's own value when it closes.
- **Symbol textbox, not a dropdown**: type and the server suggests as you go. It matches
  tickers and company names (`vishal` finds VMM), index spots, futures, option
  contracts (`NIFTY 25000 CE`, `BANKNIFTY55000PE`) and saved baskets by name. Up/Down and
  Enter pick a suggestion, Enter on free text tries it as an NSE ticker, and Escape or
  clicking away with half-typed text puts the current symbol back.
- **A colour for everything drawn**, under *Indicators & colours*: every indicator line,
  Supertrend's uptrend and downtrend separately, and up/down candles (volume follows).
  Colours apply instantly without a refetch, and *Reset colours* restores the defaults.
- **Time axis in IST**, so the open reads 09:15 rather than the UTC 03:45.
- **Remembered across reloads** in `localStorage`: chart count, each pane's symbol and
  timeframe, data source, refresh interval, axis sync, indicators and colours.
- Candles plus a volume histogram, optional time-axis sync across panes, and a refresh
  interval (off / 5s / 15s / 60s). Refreshes push only new bars via `series.update()`,
  so your zoom and pan survive.

Charts show the same candles the strategy evaluates, since both read through the same
broker — no drift between what you see and what the engine acts on. The one difference:
charts include the bar currently forming, while the strategy only ever acts on closed bars.

### Trading from a chart

Every pane has a **Trade** button (not on index spots or baskets). The ticket takes:

| Field | Choices |
|---|---|
| Side and size | Buy or Sell; lots for F&O, shares for stocks |
| Order | **Market**; **Limit** — rests at the broker until the price comes to it, and is cancelled at the no-new-entry cutoff if still unfilled; **GTT** — held by the engine until the live price reaches the trigger, then sent at market or at a limit you give |
| Stop loss | a price, or % from the entry. Blank uses the Strategy tab's stop % |
| Trailing SL | points or % behind the best price since entry. It only ever tightens; with a stop as well, the tighter of the two applies from the start |
| Trail after | trailing profit: the trail starts only once the trade is this % in profit. Blank trails from the entry |
| Target | a price, or % from the entry |
| Product | Intraday (squared off at 15:15) or Delivery (carried overnight) |
| Exit by | SL / target + exit conditions (default), SL / target only, or exit conditions only (no stop); the conditions read the chart's timeframe |

The ticket previews the entry, stop, target and rupee risk with the same arithmetic the
engine uses, and refuses a stop or target on the wrong side of the entry before anything
is sent. Once placed, the pane shows a chip with the working order or the position and its
P&L, with **Cancel** or **Exit**, and draws the entry, stop (trailing, when it has moved)
and target, or a pending GTT's trigger, as price lines. Halt, market hours, the
no-new-entry cutoff and the position and per-day caps all apply, to a GTT when it fires.

The engine enforces a trailed stop on every price check. The resting SL-M order at the
broker, the backstop for this process dying, is moved in steps of a quarter of the trail
distance rather than on every tick. A GTT lives in this process, not at the broker (Dhan's
Forever Orders support only CNC and MTF delivery, not the intraday product this engine
trades), so the app has to be running for it to fire, and it is checked at the engine's
poll interval.

---

## Baskets

A basket is a set of buy and sell legs sent together: a spread, a straddle, a hedged
future, a stock pair. Build one on the console's **Baskets** tab, where each leg is a
symbol textbox, a BUY/SELL side and a lot count (shares for stocks). Or build it from
the option chain with the B / S buttons. Lots are converted with the contract's real lot
size when the basket is saved.

| Button | What it does |
|---|---|
| **Execute** | Sends every leg now, at market or as limit orders at a price per leg, intraday or delivery, with the exit mode you pick. Halt, market hours, the position cap, per-day caps, legs already open and product rules are all checked *before* the first order, so a basket is never stopped part-way by a rule. Bought legs go first, so the hedge is in place before the sold legs need margin. Limit legs fill independently, each when its own price comes. |
| **Exit all** | Buys back sold legs first, then sells the bought ones. |
| **Watch legs** | Each leg waits for its own entry signal and raises its own approval card instead. **Stop watching** undoes it. |
| **Combo** | Opens the combo screen: underlying, combined premium, calls and puts together (below). |
| **Chart** | Opens the combined basket value with every indicator, beside each leg. |

The basket is a grouping, not a new execution path. Each leg is an ordinary watch with
its own stop (set a wider per-leg stop % for option baskets), its own exits and the
end-of-day square-off. After an Execute, the legs never raise approvals of their own. The
card shows each leg's state, entry, LTP, stop and P&L, the basket's unrealised and
realised totals, and a loud **only N of M legs open** warning when a hedge has lost a
leg, for instance after one leg's stop fired.

**The basket chart** is `basket:<id>`, charted like any symbol. Its value is the combined
premium in points, Σ(±w × price), plus for a bought leg and minus for a sold one, where w
is the leg's lots divided by the lots' common divisor: legs in equal lots chart as the
plain sum or difference of their prices, never price × lot size, and a 1:2 ratio spread
as A − 2B. The line rising is always good for you, so a short straddle plots negative and
climbs as premium decays. The basket card shows the same premium in points, and the
rupee value beside it. When every leg is on one underlying, each bar's
high and low are the combination valued at the underlying's high and low moments:
calls, futures and stock at their highs and puts at their lows, then the reverse. That
gives a range the basket could actually have traded, rather than every leg's best case
at once. VWAP, Supertrend, RSI and the rest are computed on that series.

### The combo screen

`/combo` draws a basket the way the TradingView combo script in
`trading_view_script.md` does, on four charts:

```
+----------------------+----------------------+
|  underlying spot     |  call legs           |
+----------------------+----------------------+
|  combined premium    |  put legs            |
|  VWAP, EMA 1, EMA 2, |                      |
|  Supertrend, table   |                      |
+----------------------+----------------------+
```

It follows the script's arithmetic, in premium points (lots reduced by their common
divisor, as on the basket chart): one leg is its price; two legs on the same side are
summed, on opposite sides differenced (unsigned); three or more are the signed net. The
table's P/L keeps the real lots. **Bar range** picks how the combo's high and low are inferred:
*Spot linked* (the default: the combo valued at the underlying's high, calls high and puts
low, and at its low), *Body only*, or *Sum leg wicks*. The call and put charts show the CE
and the PE legs alone, as absolute values or signed. VWAP (session), two EMAs (9, 21) and
Supertrend (factor 3, ATR 10) are computed on the combo and adjustable. The table lists
each leg's strike, side, lots, entry, LTP and P/L, then CALLS, PUTS and TOTAL, in points
or rupees. Entries come from the legs' open positions once the basket is executed.

Open it from a basket card's **Combo** button, from the option chain's **Combo chart ↗**
button (the legs on the builder, no need to save), or directly as
`/combo?basket=<id>` or `/combo?legs=opt:NIFTY:2026-10-06:25000:CE@BUY@1,...`. On a narrow
screen the four charts stack in reading order: spot, combo, calls, puts.

### Swapping the data source

`matheran/data_source.py` is the whole contract. Two methods, and the new provider shows
up in the dropdown with no other change anywhere:

```python
@register("binance", label="Binance spot")
class BinanceSource(DataSource):
    async def search(self, query, limit=40) -> list[SymbolRef]:
        ...   # feeds the symbol picker
    async def candles(self, symbol, timeframe, bars=400) -> list[Bar]:
        ...   # feeds the chart, oldest bar first
```

`Bar` is `time` (UNIX seconds), `open`, `high`, `low`, `close`, `volume`. Timeframe
strings are validated at the API boundary, so a new provider cannot forget to. A broker
used for data can also implement `history_candles(instrument, interval, start, end)`
(Upstox and Dhan do), which is what lets the 1h to 1M timeframes reach back months or
years; without it they are built from the six sessions of 1-minute candles.
A worked Binance example is at the bottom of the file, commented out.

---

## Brokers

Execution and market data are configured separately, because the cheapest source of
each is a different broker.

```yaml
broker:
  name: dhan          # who executes orders  — free on Dhan
  data_broker: upstox # who supplies candles — free on Upstox, no credentials at all
```

| Provider | Market data | Live orders | Notes |
|---|---|---|---|
| **Upstox** | **free, no credentials** | no (data only) | Candle endpoints are unauthenticated. A token is optional and only upgrades LTP to live ticks. |
| **Dhan** (DhanHQ v2) | ₹499 + tax/month | yes | Trading APIs free. Order placement needs a whitelisted static IP. Tokens last 24h. |
| **Stoxkart** (Superr) | none published | **no** | Adapter deliberately partial — see below. |
| **Paper** | synthetic | simulated | Runs with no credentials whatsoever. |

### Why Upstox for data

Upstox's V3 candle endpoints are documented as needing no authorization, and they
behave that way — verified live against both equities and option contracts. You get
1-minute OHLCV with open interest, for free, with nothing to configure:

```
GET /v3/historical-candle/intraday/{key}/minutes/1      # today
GET /v3/historical-candle/{key}/minutes/1/{to}/{from}   # prior sessions
```

The two sources line up exactly: Upstox publishes `exchange_token`, which is the same
number Dhan calls `security_id` (RELIANCE 2885, NIFTY 25000 CE 74365 — both verified).
So an instrument resolved through Dhan for order placement translates to an Upstox key
with no fuzzy symbol matching. Indices are the one exception (different tokens), and
those are matched by symbol.

Without an Upstox token the "current price" is the most recent 1-minute close, which
lags by under a minute. The protective stop resting at your execution broker is what
covers intra-minute moves, so the engine does not depend on tick-level quotes.

### Why Stoxkart is partial

Stoxkart publishes no API reference, and their two public SDKs disagree: the JavaScript
one routes orders to `/order/v1/place-order` while the Python one posts to
`/orders/normal`, with different root URLs. Neither exposes any market-data endpoint at
all. Rather than guess a payload shape and fire a malformed live order, the adapter
implements the auth handshake and refuses loudly on anything unverified.

To finish it: get the spec from Stoxkart support, diff it against
`StoxkartBroker.order_payload()`, and flip `supports_live_orders`.

Adding a provider means implementing the one `Broker` class in
`matheran/brokers/base.py`. The engine, strategy and API never import a broker module
directly, and `CompositeBroker` is what splits data from execution.

### Why Stoxkart is partial

Stoxkart publishes no API reference, and their own two public SDKs disagree: the
JavaScript one routes orders to `/order/v1/place-order` while the Python one posts to
`/orders/normal`, and they use different root URLs. Neither documents a historical-candle
or quote service. Rather than guess a payload shape and fire a malformed live order, the
adapter implements the auth handshake and refuses loudly on anything unverified. Market
data falls back to Dhan automatically when Dhan credentials are present.

To finish it: get the endpoint spec from Stoxkart support, diff it against
`StoxkartBroker.order_payload()`, and flip `supports_live_orders`.

---

## Account prerequisites

Run `run.py doctor` — it reads your broker profile and warns about these before you find
out mid-session.

| Requirement | Needed for | Cost |
|---|---|---|
| Dhan access token | Placing orders, reading positions | free, expires every 24h |
| **Derivatives (F&O) segment** | *Placing* option orders. Scanning the chain works without it, since that is read-only. | free, needs activation |
| **Static IP whitelisted** | Placing orders only | SEBI requirement |
| Dhan Data APIs | Nothing, if `data_broker: upstox` | ₹499 + tax/month |

With `data_broker: upstox` you do not need the Dhan Data API subscription at all. If you
do point `data_broker` at Dhan without it, every candle request returns `806 / DH-902`
and the adapter turns that into a plain-English error naming the fix, surfaced as a
banner in the console rather than retried forever.

Dhan access tokens last **24 hours**. Paste a fresh one into the Setup tab each day, or
set up TOTP and script `auth.dhan.co/app/generateAccessToken`.

---

## Safety

- **Paper by default.** Switching to live needs an explicit confirmation in the UI and a
  `confirm_live: true` flag on the API.
- **Loopback by default.** Binding anywhere else refuses to start without `MATHERAN_API_KEY`.
  Credential and config endpoints are rejected outright from non-local peers.
- **Secrets stay server-side.** The UI only ever receives "is set" plus the last four
  characters. `.env` is written atomically at mode `0600`.
- **Caps** on trades per day per watch, concurrent positions, and a no-new-entries cutoff.
- **Broker swaps are refused** while an order or position is open, so nothing gets orphaned.
- **Restart adoption.** On startup the engine reconciles against broker positions and
  adopts anything still open rather than leaving it unmanaged.
- **Rate limiting** with token buckets sized to Dhan's published limits (order 10/s,
  data 5/s, quote 1/s), plus candle caching and batched quote calls.

- **One exit at a time.** A second Exit while the first order is in flight is refused
  rather than sent, since it would sell twice and leave the account short.

Every order carries its product: `INTRADAY`, or `DELIVERY`, which Dhan receives as `CNC`
for shares and `MARGIN` (NRML) for futures and options. A position's stop, exit and
square-off orders use the product it was opened with. Shares can only be sold short
intraday; a carried short has to be a future or an option. On restart a short adopted
from the broker takes its entry from Dhan's sell average, and in paper mode the simulated
positions are restored: delivery ones always, intraday ones on the day they were opened.

Not handled: exchange holidays (the engine simply finds no fresh candles) and SEBI's
algo-ID registration, which is between you and your broker.

---

## Layout

```
run.py                      CLI: serve / selfcheck / doctor / chain / scan
config.example.yaml          copy to config.yaml (the UI writes this file)
.env.example                 copy to .env (or let the UI create it)
matheran/
  indicators.py              VWAP, RSI, EMA, RMA, ATR, Supertrend, ADX  (TradingView semantics)
  candles.py                 candle model, epoch normalisation, resampling (minutes to months), bar close times
  timeframes.py              the timeframe table, and loading candles at any of them (recent feed + history)
  chart_types.py             Heikin Ashi and Renko
  strategy.py                entry/exit rules, reported condition by condition
  rules.py                   exit conditions as rows: catalog, validation, mirroring, evaluation
  engine.py                  per-watch state machine, approvals, stops, trailing, GTT, square-off, reconciliation
  options.py                 ATM/OTM chain selection and the scan table
  scanner.py                 the live BUY/SELL scanner: rows per timeframe, plan, evaluation, scan jobs
  scan_data.py               scanner data: targets, the disk history cache, request budget, quotes, run lock
  universes.py               scanner universes: index lists (allowlisted NSE sources), custom symbols
  universe_snapshot/         dated offline copy of the eight index CSVs, with manifest.json
  settings.py                .env and config.yaml management, secret masking
  data_source.py             pluggable chart feeds — add a broker by adding one class
  api.py                     FastAPI routes
  baskets.py                 basket legs, storage, and the combined value series
  combo.py                   the TradingView combo script's arithmetic: combo, call and put baskets
  chart_indicators.py        indicator series for the charts, same maths as the engine
  dashboard.py               the console (single file, no build step)
  charts_page.py             the multi-pane chart grid with the trade ticket (plain HTML/CSS)
  chain_page.py              the one-page option chain with the basket builder
  combo_page.py              the 2 × 2 basket combo screen
  static/                    vendored Lightweight Charts v5.2.1 (Apache-2.0)
  brokers/base.py            the interface to implement
  brokers/composite.py       splits market data and order execution across two brokers
  brokers/dhan.py            DhanHQ v2 (execution + optional paid data)
  brokers/upstox.py          Upstox market data (free, unauthenticated)
  brokers/stoxkart.py        Superr API (partial)
  brokers/paper.py           simulated fills, synthetic feed
  store.py                   watches.json + trades.jsonl, atomic writes
  selfcheck.py               indicator validation
```

---

## Verification

`run.py selfcheck` ships with the project (80 checks). During development the engine,
HTTP and settings layers were also verified and all passed:

| Suite | Checks | Covers |
|---|---|---|
| selfcheck | 80 | indicators vs an independent reference implementation (ZEMA included), resampling into minutes, hours, days, weeks and months, bar close times, Heikin Ashi, Renko, basket premium weights, tick rounding, 3% stop maths, VWAP with and without volume, strategy wiring, scanner rows, mirroring, sessions, cache reuse and the request budget |
| engine | 62 | full lifecycle, target/stop/indicator/square-off exits, approval expiry, rejection, market-hours and daily caps, halt, broker-stop failure, restart adoption, persistence |
| api | 74 | auth, watch CRUD, diagnostics, options chain shape, option lot sizing, approvals, controls |
| settings | 83 | `.env` parsing and 0600 permissions, masking, clear-vs-untouched semantics, config validation and rollback, live-mode guard, key generation taking effect immediately, broker swap refusal while in position |
| no-data safety | 27 | no approval, order, position or trade is ever produced when the feed errors, returns nothing, or falls short of the indicator warmup — with a control proving a healthy feed *does* raise one |
| upstox / composite | 51 | live candle fetch with no credentials, Dhan↔Upstox token mapping for equity/option/index, indicator values on real data, 12-leg chain scan, caching, composite routing |
| charts | 59 | every grid layout is the requested shape, only the five counts offered, layout persisted and validated on read, per-pane independence, v5 API used and v4 helper absent, library vendored not CDN, a third-party source registering by decorator alone, live candles at 1m/5m/15m with correct spacing and OHLC consistency, bad timeframe and unknown symbol rejected |

Verified against live market data on 2026-09-29, including a full NIFTY chain scan and
indicators on RELIANCE and TCS.

Not verified: live order placement against a funded account, and the Stoxkart
endpoints. Both need access I do not have.

---

## This is not financial advice

You are automating your own decisions. Backtest the logic, run it in paper mode across
several sessions, and read the approval card before pressing the button.
