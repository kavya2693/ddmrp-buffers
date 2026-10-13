# ddmrp-buffers

[![ci](https://github.com/kavya2693/ddmrp-buffers/actions/workflows/ci.yml/badge.svg)](https://github.com/kavya2693/ddmrp-buffers/actions/workflows/ci.yml)
![python](https://img.shields.io/badge/python-3.11-blue)
![license](https://img.shields.io/badge/license-MIT-lightgrey)

How much stock a lubricants distributor can release by switching to demand-driven
replenishment buffers, measured at the same service level its customers get today.

## The problem

A regional lubricants distributor carries about 800 SKUs: the same engine oil grade in a
1 L bottle, a 4 L jug, a 20 L pail, a 208 L drum and a 1,000 L IBC, plus greases, coolants
and hydraulic oils. Most of it is blended and filled locally on a one-to-two-week cycle.
About a quarter is imported finished goods with lead times of six weeks to three months,
and one shipment in ten sits at the port for a few more weeks.

Purchasing runs on min-max levels that were set once a year from last year's average,
with a month of safety cover and three to six months of extra cover on top. The result is
the familiar one: months of stock in the warehouse, much of it on SKUs that barely sell,
and still a stockout when a fleet customer orders forty drums at once. Every day of
inventory is cash the finance team cannot use, and every lost order goes to a competitor.

## Why it is hard

Cutting stock is easy; cutting stock without losing customers is not. Any policy that
holds less will show a lower days-inventory-outstanding figure, so DIO on its own proves
nothing. And beating a legacy rule that is reset once a year is also easy: almost any
policy that is recalculated weekly will do it. The real question is whether demand-driven
buffers (DDMRP) beat a properly tuned classical policy, and what each of them costs in
fill rate and purchasing workload.

## The approach

The range is simulated day by day for two years under five replenishment policies, all
facing identical demand, identical opening stock and identical supplier delays. DDMRP is
implemented in full: average daily usage over 84 days, lead-time factors by lead-time band,
variability factors from weekly demand variation, red, yellow and green zones, the net flow
equation (on hand + on order − qualified demand, where large customer orders already placed
count against the buffer before they ship), and order generation up to top of green,
rounded to case and minimum order quantity. A slow-mover classifier splits SKUs into
runners, repeaters, strangers and dormant items by how often they sell.

The key decision ([ADR-0001](docs/adr/0001-compare-at-matched-service.md)) was to judge
policies **at matched service**. The tuned reorder point and DDMRP are each swept over their
one safety knob, and stock is read off at the fill rate the legacy policy already delivers.

## The result

Year 2 of the simulation (2025), after the opening overstock of 172 days has worked
through. Value fill rate is the share of demand value shipped on the day it was due.

| Policy | DIO (days) | Avg stock at cost | Value fill rate | Stockout SKU-days | POs per month |
|---|---:|---:|---:|---:|---:|
| Min-max (legacy, reset yearly) | 97.6 | 11.96 M | **98.46%** | 0.33% | 195 |
| Reorder point (tuned, weekly) | 40.1 | 4.72 M | 94.51% | 1.26% | 1,039 |
| DDMRP | 39.9 | 4.79 M | 96.61% | 0.62% | 1,004 |
| DDMRP without open-order visibility | 39.8 | 4.68 M | 94.49% | 0.95% | 1,002 |
| DDMRP + slow-mover rule | 37.1 | 4.39 M | 95.21% | 0.85% | 1,084 |

**The metrics disagree.** At default settings DDMRP cuts DIO from 97.6 to 39.9 days, but
fill rate falls from 98.46% to 96.61% and lost sales more than double (0.70 M to 1.54 M at cost). Reported on DIO alone, that is
a 59% improvement; it is not.

**At matched service the gain is still large, and smaller.** Read at the legacy policy's
own 98.46% fill rate:

| Policy | DIO at 98.46% fill | Change vs legacy |
|---|---:|---:|
| Min-max (legacy) | 97.6 | |
| Reorder point (tuned) | 65.9 | −32% |
| DDMRP | 52.1 | −47% |

![Stock held for a given service level](outputs/frontier.png)

Repeated on three freshly generated ranges with fresh lead-time draws, DDMRP holds
51.7 to 59.6 days at the legacy fill rate against 97.6 to 108.2 days for legacy min-max.
The tuned reorder point needs 65.9 to 74.1 days, and on one seed never reaches the legacy
fill rate within the sweep (z up to 5.5).

Three findings that the headline hides:

1. **About 70% of the stock reduction comes from recalculating weekly, not from DDMRP.**
   A tuned reorder point already gets DIO from 97.6 to 65.9 days at the same fill rate;
   DDMRP adds the remaining 13.8 days.
2. **DDMRP's edge over the reorder point is the net flow equation.** With open-order
   visibility switched off, DDMRP lands on the reorder point's numbers (39.8 days,
   94.49% fill). In this range 13.6% of demand value arrives as bulk fleet orders placed
   3 to 21 days ahead; a distributor with less advance visibility would see less benefit.
3. **The slow-mover rule buys cash with service on strangers.** Holding only a red zone
   on SKUs that sell on fewer than one day in ten frees a further 0.4 M, but their fill rate
   drops from 92.05% to 78.72%. That is a commercial decision, not a free win.

The cost on the other side is purchasing workload: weekly-recalculated policies raise
purchase orders from about 195 to about 1,000 a month, mostly small local blend orders.

`outputs/results.md` has year 1, both years, every segment (local blend vs import, and each
slow-mover class) and the full sweep.

## How it works

```
data/ (skus, daily demand, bulk orders, opening stock)
  │
  ▼
simulate.py ── for each day ──► receive arrivals ─► ship demand (unfilled is lost)
  │                              ─► policy.order(stock, on order, open customer orders)
  │                              ─► place order with this day's realised lead time
  ▼
policies.py   legacy min-max · tuned reorder point · DDMRP (± spikes, ± slow-mover rule)
buffers.py    ADU, LTF, VF, zones, net flow, order up to top of green
classify.py   runner / repeater / stranger / dormant from sale frequency and recency
metrics.py    DIO, stock at cost, value fill rate, stockout SKU-days, POs, matched-service DIO
cli.py        runs every policy, the safety sweeps and three extra seeds; writes outputs/
```

Buffers are recalculated every seven days. A customer order counts against the buffer
early when it is at least half the red zone and due within the decoupled lead time.
Strangers under the slow-mover rule keep only the red zone and are bought in the quantity
needed; dormant SKUs hold nothing and are bought only against an order in hand.

![DDMRP buffer for three SKUs](outputs/buffer_chart.png)

The top panel is a local-blend runner: on-hand cycles through the green and yellow zones
once the opening overstock is gone. The middle panel is an imported runner with a 79-day
lead time; the 34 days at zero in August 2024 follow two orders that took 118 and 100
days to arrive against a nominal 79. The bottom is a stranger that sells one IBC every few weeks.

![Working capital in stock](outputs/inventory_value.png)

## Running it

```bash
uv sync
make data     # writes data/skus.csv, data/demand.csv.gz, data/bulk_orders.csv (seed 20240101)
make run      # all policies, sweeps and extra seeds; tables and charts to outputs/ (~20 s)
make check    # ruff, format, mypy, pytest
docker build -t ddmrp-buffers . && docker run --rm ddmrp-buffers
```

Policy constants (zone factors, windows, order cycles, slow-mover thresholds) are in
`src/ddmrp_buffers/config.py`. No API key, model or network access is needed.

## The data

The dataset is generated by the seeded script `scripts/generate_data.py` and sized to the
production problem (800 SKUs, three years of daily demand); production data is
proprietary. It carries an annual season by product family, a quiet weekday, public
holidays, a fasting month and post-holiday restocking, heavy-tailed volumes, growing,
declining, phased-out and newly launched SKUs, 4,702 bulk fleet orders announced 3 to 21
days ahead, and 4.7% missing days in the first year's ERP extract, including a ten-day
outage. Opening stock reflects a range run on generous cover: 21.5 M at cost, 172 days of
trailing usage. 2023 is history only; 2024 and 2025 are simulated.

## Tests

`make check` runs 19 tests. The two that matter most:

- `test_zones_match_hand_worked_example` checks the zone arithmetic, net flow and case
  rounding against a buffer worked out by hand (ADU 10, DLT 10, LTF 0.7, VF 0.5 gives
  TOR 105, TOY 205, TOG 275, and a net flow of 140 orders 144 units). It was written
  before the simulation existed.
- `test_stock_balance_holds_every_day` checks for each policy that closing stock equals
  opening stock plus receipts minus shipments on every day and SKU, that nothing arrives
  that was not ordered, and that stock never goes negative.

Others cover open-order qualification (placed, due, horizon, threshold), the classifier,
the KPI arithmetic, matched-service interpolation, generator determinism and a steady
demand SKU that must never stock out under DDMRP.

## Known limitations

- **The biggest gap: the data is generated, so the size of DDMRP's edge depends on
  choices I made.** In particular, its advantage over the reorder point comes from bulk
  orders being visible in advance. The share and the notice period are assumptions, not
  measurements; with real order books the gap could be larger or close to zero.
- Single stocking point. No blending capacity, shared base oils or filling-line schedule,
  so a local blend is assumed to be available on its lead time whatever else is running.
- No planned adjustment factors for seasonality; buffers follow a trailing 84-day ADU and
  lag the start of a season. Coolant, the most seasonal family, drops to 93-96% fill in
  several spring and summer months against about 99% in winter.
- The slow-mover rule assumes strangers can be bought below the usual MOQ. If the blend
  plant or supplier will not accept that, the rule frees less cash.
- Purchase order counts are reported but not costed; there is no ordering or freight cost
  in the objective.
- Disposal of dead stock is not modelled. Opening stock on dormant SKUs stays on the
  books under every policy; releasing it takes a write-off or a sale, not a buffer.
- The Docker image is built and run in CI; it could not be built on the development machine.

## Insights and learning

I picked this because a DIO number on a resume invites the obvious question: how much
service did you give up for it? Building the comparison properly answered that, and the
answer was not the one I expected going in. I assumed DDMRP's benefit would come from the
zone sizing. The ablation says otherwise: with the same window, the same recalculation
cadence and the same order cycle, a textbook reorder point is as good at sizing stock, and
DDMRP pulls ahead because its net flow equation counts orders customers have already
placed. That is a practice any planning team could adopt without the rest of the method.

The second surprise was how much of the cash comes from discipline rather than method.
Recalculating weekly instead of yearly does most of the work. The DDMRP-specific gain is
real but it is the smaller part, and the purchasing team pays for both in order volume.

What I got wrong first: the initial version compared DDMRP only with legacy min-max and
reported DIO, which made it look like a 59% reduction for free. Adding fill rate and the
tuned baseline is what made the result defensible. Next I would add seasonal adjustment
factors to the buffers, cost purchase orders and freight so the comparison has one
objective, and test the open-order effect on a real order book.

## License

MIT
