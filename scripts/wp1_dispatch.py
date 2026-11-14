"""WP1: hourly dispatch of today's system (gas CHP + gas boilers) on real 2023-2025 prices and Dresden weather,
and the same system with one heat pump and a heat storage tank added: which unit runs when, and why.

Outputs: results/wp1/*.csv, figures/wp1_dispatch.png
"""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from fernwaerme import checks, data as D, model as M

OUT = D.ROOT / "results" / "wp1"
FIG = D.ROOT / "figures"
OUT.mkdir(parents=True, exist_ok=True)
FIG.mkdir(exist_ok=True)

ADD = {"hp_air": [50.0], "tank": [1500.0]}   # one 50 MW air-source heat pump and a 1,500 MWh tank (illustrative)


def run(year: int, builds: dict):
    cfg = D.load_config(overrides={"step_hours": 1})
    ys = M.year_inputs(cfg, [year], [0.0])
    checks.check_inputs(cfg, ys)
    m = M.build(cfg, ys, integer=False, fixed_builds={k: builds.get(k, [0.0]) for k in M.NEW})
    info = M.solve(m)
    res = M.results(m)
    chk = checks.check_solution(m, cfg)
    d = M.dispatch_frame(m)
    return info, res, chk, d, ys[0]


def main():
    rows, disp = [], {}
    for year in (2023, 2024, 2025):
        for case, b in (("today", {}), ("plus_hp_tank", ADD)):
            info, res, chk, d, y = run(year, b)
            e = res["energy_gwh"].iloc[0]
            chp_on = d.gas_chp > 1
            rows.append({"year": year, "case": case, "gas": y.gas, "co2": y.co2, "mean_power_price": d.power_price.mean(),
                         "chp_gwh": e.gas_chp, "boiler_gwh": e.gas_boiler, "hp_gwh": e.hp_air, "storage_out_gwh": e.storage_out,
                         "chp_full_load_hours": e.gas_chp * 1000 / 120,
                         "price_when_chp_runs": d.power_price[chp_on].mean(),
                         "price_when_hp_runs": d.power_price[d.hp_air > 1].mean() if (d.hp_air > 1).any() else float("nan"),
                         "annual_cost_meur": res["costs"].annual_cost_meur.iloc[0],
                         "heat_cost_eur_mwh": res["costs"].heat_cost_eur_mwh.iloc[0],
                         "checks": checks.summary(chk), "status": info["status"]})
            disp[(year, case)] = d
            d.to_csv(OUT / f"dispatch_{year}_{case}.csv")
    df = pd.DataFrame(rows)
    df.to_csv(OUT / "summary.csv", index=False)
    print(df.drop(columns=["checks"]).round(1).to_string())
    print(df[["year", "case", "checks"]].to_string())
    plot(disp)


def plot(disp):
    fig, axes = plt.subplots(3, 1, figsize=(12, 10), sharex=False)
    cols = {"gas_chp": "tab:orange", "gas_boiler": "tab:red", "hp_air": "tab:green", "tank_out": "tab:blue"}
    for ax, (case, a, b, title) in zip(axes[:2], [("today", "2024-01-08", "2024-01-21", "today's system"),
                                                    ("plus_hp_tank", "2024-01-08", "2024-01-21", "with a 50 MW heat pump and a 1,500 MWh tank")]):
        d = disp[(2024, case)].loc[a:b]
        bottom = 0
        for c, col in cols.items():
            v = d[c].clip(lower=0)
            ax.fill_between(d.index, bottom, bottom + v, color=col, step="mid", alpha=0.8, label=c.replace("_", " "))
            bottom = bottom + v
        ax.plot(d.index, d.demand, "k", lw=0.8, label="demand")
        ax2 = ax.twinx()
        ax2.plot(d.index, d.power_price, color="grey", lw=0.6, ls="--")
        ax2.set_ylabel("day-ahead price (EUR/MWh)", fontsize=8)
        ax.set_ylabel("heat (MW)")
        ax.set_title(f"Two winter weeks 2024, {title}", fontsize=9)
        ax.legend(fontsize=7, loc="upper left", ncol=5)
    ax = axes[2]
    d = disp[(2024, "plus_hp_tank")]
    ax.scatter(d.power_price, d.gas_chp, s=2, color="tab:orange", label="gas CHP")
    ax.scatter(d.power_price, d.hp_air, s=2, color="tab:green", label="heat pump")
    ax.set_xlim(-50, 300)
    ax.set_xlabel("day-ahead price (EUR/MWh)")
    ax.set_ylabel("heat output (MW)")
    ax.set_title("2024, every hour: the CHP runs at high prices, the heat pump at low prices", fontsize=9)
    ax.legend(fontsize=7)
    fig.tight_layout()
    fig.savefig(FIG / "wp1_dispatch.png", dpi=140)


if __name__ == "__main__":
    main()
