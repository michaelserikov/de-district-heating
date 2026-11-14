"""WP4: data and model quality, solver behaviour.

1. Time resolution: the 2045 system (100% non-fossil) optimised at 1, 3 and 6 hour steps: cost and sizes.
2. Solver: dual simplex vs interior point on the same LP; LP relaxation vs MILP (from WP2/3 results).
3. Diagnosis instead of "infeasible": a 2045 case that cannot meet demand (no new heat pumps, little biomass)
   solves with priced slack and reports when and how much heat is missing.
4. Input checks: a temperature series with a gap or a falling target is stopped before the solve.
Outputs: results/wp4/*.csv
"""
from __future__ import annotations

import pandas as pd

from fernwaerme import checks, data as D, model as M

OUT = D.ROOT / "results" / "wp4"
OUT.mkdir(parents=True, exist_ok=True)


def year2045(cfg, step):
    cfg = D.with_overrides(cfg, step_hours=step)
    ys = M.year_inputs(cfg, [2045], [1.0])
    # a single milestone stands alone: use 2045 scenario prices, CHP retired
    return cfg, ys


def resolution():
    rows = []
    for step in (6, 3, 1):
        cfg, ys = year2045(D.load_config(), step)
        m = M.build(cfg, ys, integer=False)
        info = M.solve(m, time_limit=1800)
        r = M.results(m)
        cap = r["capacity_mw"].iloc[0]
        rows.append({"step_h": step, "status": info["status"], "seconds": info["seconds"],
                     "annual_cost_meur": r["costs"].annual_cost_meur.iloc[0],
                     **{f"cap_{k}": cap[k] for k in ("hp_air", "hp_sewage", "biomass", "e_boiler", "tank", "pit")},
                     "checks": checks.summary(checks.check_solution(m, cfg))})
        print(rows[-1], flush=True)
    df = pd.DataFrame(rows)
    df.to_csv(OUT / "resolution.csv", index=False)
    return df


def solvers():
    rows = []
    cfg, ys = year2045(D.load_config(), 3)
    for method in ("simplex", "ipm"):
        m = M.build(cfg, ys, integer=False)
        info = M.solve(m, method=method)
        rows.append({"method": method, **info})
    m = M.build(cfg, ys, integer=True)
    info = M.solve(m, mip_gap=0.005, time_limit=1200)
    rows.append({"method": "MILP (modules)", **info})
    df = pd.DataFrame(rows)
    df.to_csv(OUT / "solvers_2045.csv", index=False)
    print(df.to_string(), flush=True)


def diagnosis():
    cfg = D.load_config(overrides={"step_hours": 3})
    ys = M.year_inputs(cfg, [2045], [1.0])
    m = M.build(cfg, ys, integer=False)
    # e.g. the grid connection allows only 60 MW of air-source heat pumps and no electric boiler, no new tank
    for k, v in (("hp_air", 60.0), ("e_boiler", 0.0), ("tank", 0.0)):
        m.b[k, 0].fix(v)
    info = M.solve(m)
    d = M.dispatch_frame(m)
    chk = checks.check_solution(m, cfg)
    miss = d[d.unserved > 1e-3]
    out = {"status": info["status"], "unserved_gwh": float(d.unserved.sum() * 3 / 1000),
           "hours_short": int(len(miss) * 3), "peak_shortfall_mw": float(d.unserved.max()),
           "months": sorted(set(miss.index.month)),
           "t_air_mean_when_short": float(D.aggregate(D.temperature(cfg["weather_year"]), 3).reindex(miss.index).mean()) if len(miss) else None,
           "checks": checks.summary(chk)}
    pd.Series(out).to_csv(OUT / "diagnosis_unserved.csv")
    print(out, flush=True)


def input_checks():
    rows = []
    cfg = D.load_config(overrides={"step_hours": 6})
    ys = M.year_inputs(cfg, [2030, 2035], [0.3, 0.3])
    bad = ys[0].demand.copy()
    bad.iloc[100] = float("nan")
    ys[0].demand = bad
    try:
        checks.check_inputs(cfg, ys)
        rows.append(("gap in demand", "not caught"))
    except checks.InputError as e:
        rows.append(("gap in demand", "stopped: " + " ".join(str(e).splitlines()[2].split())))
    ys = M.year_inputs(cfg, [2030, 2035], [0.8, 0.3])
    try:
        checks.check_inputs(cfg, ys)
        rows.append(("falling target", "not caught"))
    except checks.InputError as e:
        rows.append(("falling target", "stopped: " + " ".join(str(e).splitlines()[2].split())))
    df = pd.DataFrame(rows, columns=["case", "result"])
    df.to_csv(OUT / "input_checks.csv", index=False)
    print(df.to_string(), flush=True)


if __name__ == "__main__":
    input_checks()
    diagnosis()
    solvers()
    resolution()
