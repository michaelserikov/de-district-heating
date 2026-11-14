"""WP2 and WP3: the transformation pathway 2030-2045 under the WPG targets, scenarios and sensitivities.

Central case as MILP (heat pumps, biomass and electric boilers in modules); every scenario also as LP (continuous
sizes) so that differences come from the inputs, not from the branch-and-bound tolerance. Indicators: NPV of
system cost 2026-2049, discounted heat generation cost (EUR/MWh), capacity in 2045, builds by 2030.
Outputs: results/wp23/*.csv, figures/wp3_tornado.png, figures/wp2_pathway.png
"""
from __future__ import annotations

import json
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from fernwaerme import data as D, model as M
from fernwaerme.run import run_pathway, save

OUT = D.ROOT / "results" / "wp23"
OUT.mkdir(parents=True, exist_ok=True)

SCENARIOS = {  # name: (overrides, label)
    "central": ({}, "central"),
    "prices_low": ({"prices.scenario": "low"}, "gas, CO2, power: low"),
    "prices_high": ({"prices.scenario": "high"}, "gas, CO2, power: high"),
    "grid_20": ({"prices.grid_charges_eur_mwh": 20}, "grid charges 20 EUR/MWh"),
    "grid_70": ({"prices.grid_charges_eur_mwh": 70}, "grid charges 70 EUR/MWh"),
    "bew": ({"subsidy.bew_invest_share": 0.4, "subsidy.bew_hp_operating_eur_mwh": 30}, "BEW: 40% capex, 30 EUR/MWh HP"),
    "no_sewage": ({"cop.sewage_potential_mw": 0}, "no waste-water heat"),
    "biomass_100": ({"prices.biomass_limit_gwh": 100}, "biomass limit 100 GWh"),
    "low_temp": ({"network_temperature.supply_cold_c": 85, "network_temperature.supply_warm_c": 65,
                  "network_temperature.return_c": 40}, "network 10 K colder"),
    "no_pit": ({"limits.pit_max_mwh": 0}, "no pit storage"),
    "chp_2045": ({"pathway.chp_retire_after": 2045}, "CHP kept to 2045"),
}


def indicators(name, info, res, cfg):
    e, c, cap = res["energy_gwh"], res["costs"], res["capacity_mw"]
    r = cfg["discount_rate"]
    disc = [(1 + r) ** -(y - 2026) for y in e.index]
    lcoh = sum(d * c.annual_cost_meur[y] * 1e6 for d, y in zip(disc, e.index)) / sum(d * e.demand[y] * 1e3 for d, y in zip(disc, e.index))
    row = {"scenario": name, "npv_meur": float(res["npv_meur"].iloc[0, 0]), "heat_cost_eur_mwh": lcoh,
           "status": info["status"], "gap": info["gap"], "seconds": info["seconds"],
           "checks_ok": bool(res["checks"].ok.all())}
    row |= {f"cap2045_{k}": cap.loc[2045, k] for k in cap.columns}
    row |= {f"cap2030_{k}": cap.loc[2030, k] for k in ("hp_air", "hp_sewage", "biomass", "pit", "tank")}
    row |= {f"gwh2045_{k}": e.loc[2045, k] for k in ("hp_air", "hp_sewage", "biomass", "e_boiler", "gas_boiler")}
    return row


def main(only=None):
    rows = []
    names = only or list(SCENARIOS)
    for name in names:
        ov, _ = SCENARIOS[name]
        cfg = D.load_config(overrides=ov)
        m, info, res = run_pathway(cfg, integer=False)
        save(f"wp23/lp_{name}", info, res, cfg)
        rows.append(indicators(name, info, res, cfg) | {"model": "LP"})
        print(name, "LP", round(rows[-1]["npv_meur"], 1), info["status"], round(info["seconds"]), flush=True)
    df = pd.DataFrame(rows)
    df.to_csv(OUT / "scenarios_lp.csv", index=False)
    if "central" in names:
        cfg = D.load_config()
        m, info, res = run_pathway(cfg, integer=True, mip_gap=0.01)
        save("wp23/milp_central", info, res, cfg)
        mi = indicators("central", info, res, cfg) | {"model": "MILP"}
        pd.DataFrame([mi]).to_csv(OUT / "central_milp.csv", index=False)
        print("central MILP", round(mi["npv_meur"], 1), info, flush=True)
    plot(df)


def plot(df):
    base = df.set_index("scenario").loc["central", "npv_meur"]
    d = df[df.scenario != "central"].copy()
    d["delta"] = d.npv_meur - base
    d["label"] = d.scenario.map(lambda s: SCENARIOS[s][1])
    d = d.sort_values("delta")
    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.barh(d.label, d.delta, color=["tab:green" if v < 0 else "tab:red" for v in d.delta])
    ax.axvline(0, color="k", lw=0.7)
    ax.set_xlabel(f"change in NPV of system cost 2026-2049 vs central ({base:.0f} MEUR)")
    ax.set_title("Which assumption moves the cost of the transformation most (LP, 6-hour steps)", fontsize=9)
    fig.tight_layout()
    fig.savefig(D.ROOT / "figures" / "wp3_tornado.png", dpi=140)


if __name__ == "__main__":
    main(sys.argv[1:] or None)
