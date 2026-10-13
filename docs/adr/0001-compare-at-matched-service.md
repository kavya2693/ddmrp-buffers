# ADR-0001: Judge replenishment policies at matched service, against a tuned baseline

## Status
Accepted

## Context
The claim to test is that demand-driven buffers let a lubricants distributor carry far less
stock. Two easy ways to make that claim look true without it being true:

1. Compare DDMRP against the legacy min-max rule only. Legacy parameters are reset once a
   year and carry months of extra cover, so almost any weekly-recalculated policy beats
   them on stock. The gain would belong to recalculation, not to DDMRP.
2. Report days inventory outstanding alone. Any policy that holds less stock and loses
   more sales lowers DIO. A lower DIO bought with lost customers is not an improvement.

Prior art does not settle this. The most used open implementation (OCA/ddmrp, an Odoo
module) computes buffers inside an ERP; it does not compare them with anything.
The other public repositories found are installers, theses or calculators.

## Decision
- Five policies run against identical demand, identical opening stock and identical
  supplier lead-time draws: legacy min-max, a tuned reorder point (z-sigma safety stock,
  weekly recalculation, same 84-day window and order cycle as DDMRP), DDMRP, DDMRP without
  open-order visibility, and DDMRP with a slow-mover rule.
- DIO and stock value are always reported next to value fill rate, stockout SKU-days and
  purchase orders per month.
- The headline comparison is stock **at matched service**: the reorder point (z) and DDMRP
  (red-zone multiplier) are each swept over their safety knob, and DIO is interpolated at
  the legacy policy's own fill rate.
- The experiment is repeated on three fresh ranges with fresh lead-time draws.
- Unfilled demand is lost, not backordered: a workshop that cannot get a drum buys it
  from another distributor.

## Alternatives rejected
- **Forecast-driven MRP as the baseline.** It needs a forecasting model whose quality
  would then dominate the comparison. A reorder point with a statistical safety stock is
  the honest classical comparator for independent-demand finished goods.
- **Backorders instead of lost sales.** Flatters every policy: late demand is still
  shipped eventually and fill rate stops measuring what customers experience.
- **Optimising DDMRP factors per SKU.** Would beat any fixed-rule baseline by construction.
  Factors stay at textbook band values.

## Consequences
- The README leads with the trade-off, not with the DIO reduction.
- The ablation shows where DDMRP's advantage over the tuned reorder point comes from
  (open-order visibility in the net flow equation), which any reorder-point system could
  also adopt.
