"""Inline the exported purchase-order sheet into compositions/value.html (renders cannot fetch files).

Usage: python3 tools/inject_sheet.py assets/po_sheet.json compositions/value.html \
         --rows LUB-0022,LUB-0304,LUB-0540,LUB-0079,LUB-0788,LUB-0035 \
         --animate LUB-0022,LUB-0304,LUB-0079,LUB-0035
"""

import argparse
import json
import re

ap = argparse.ArgumentParser()
ap.add_argument("sheet")
ap.add_argument("html")
ap.add_argument("--rows", required=True, help="SKUs shown as sheet rows, in order")
ap.add_argument("--animate", required=True, help="SKUs shown as buffers in the 2D scene (max 4)")
a = ap.parse_args()

with open(a.sheet) as fh:
    d = json.load(fh)
by_sku = {r["sku"]: r for r in d["rows"]}
rows = a.rows.split(",")
anim = a.animate.split(",")
keep = (
    "sku",
    "family",
    "pack_litres",
    "source",
    "lead_time_days",
    "due",
    "on_hand",
    "on_order",
    "customer_orders",
    "net_flow",
    "tor",
    "toy",
    "tog",
    "zone",
    "priority_pct",
    "order_qty",
    "triggered_by_customer_orders",
)
slim = {
    "day": d["day"],
    "weekday": d["weekday"],
    "orders": d["orders"],
    "imports": d["imports"],
    "with_customer_orders": d["with_customer_orders"],
    "order_value": round(d["order_value"], 2),
    "rows": [{k: by_sku[s][k] for k in keep} | {"animate": anim.index(s) if s in anim else -1} for s in rows],
}
with open(a.html) as fh:
    html = fh.read()
block = "/* SHEET:BEGIN */ const SHEET = " + json.dumps(slim, separators=(",", ":")) + "; /* SHEET:END */"
html, n = re.subn(r"/\* SHEET:BEGIN \*/.*?/\* SHEET:END \*/", lambda _: block, html, flags=re.S)
assert n == 1, "marker not found"
with open(a.html, "w") as fh:
    fh.write(html)
print("injected", len(slim["rows"]), "rows,", len(anim), "animated")
