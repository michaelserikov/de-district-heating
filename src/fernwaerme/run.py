"""Command line entry: run a scenario from the configuration and write its results.

    python -m fernwaerme.run pathway --name central
    python -m fernwaerme.run pathway --name high_prices --set prices.scenario=high
    python -m fernwaerme.run year --year 2024 --set step_hours=1

Results go to results/<name>/ (CSV) with a one-line check summary printed at the end.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

from . import checks, data as D, model as M

RESULTS = D.ROOT / "results"


def parse_sets(items: list[str]) -> dict:
    out = {}
    for it in items or []:
        k, v = it.split("=", 1)
        out[k] = yaml.safe_load(v)
    return out


def run_pathway(cfg: dict, integer: bool = True, mip_gap: float = 0.005, fixed_builds: dict | None = None):
    pw = cfg["pathway"]
    ys = M.year_inputs(cfg, pw["years"], pw["non_fossil_share"])
    checks.check_inputs(cfg, ys)
    m = M.build(cfg, ys, integer=integer, fixed_builds=fixed_builds)
    info = M.solve(m, mip_gap=mip_gap)
    res = M.results(m)
    res["checks"] = checks.check_solution(m, cfg)
    return m, info, res


def run_year(cfg: dict, year: int, non_fossil: float = 0.0, fixed_builds: dict | None = None, integer: bool = True):
    ys = M.year_inputs(cfg, [year], [non_fossil])
    checks.check_inputs(cfg, ys)
    m = M.build(cfg, ys, integer=integer, fixed_builds=fixed_builds)
    info = M.solve(m)
    res = M.results(m)
    res["checks"] = checks.check_solution(m, cfg)
    return m, info, res


def save(name: str, info: dict, res: dict, cfg: dict) -> Path:
    out = RESULTS / name
    out.mkdir(parents=True, exist_ok=True)
    for k, v in res.items():
        v.to_csv(out / f"{k}.csv")
    (out / "solve.json").write_text(json.dumps(info, indent=1, default=str))
    (out / "config_used.yaml").write_text(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=["pathway", "year"])
    ap.add_argument("--name", default=None)
    ap.add_argument("--year", type=int, default=2024)
    ap.add_argument("--non-fossil", type=float, default=0.0)
    ap.add_argument("--lp", action="store_true", help="LP relaxation (continuous unit sizes)")
    ap.add_argument("--config", default=str(D.CONFIG))
    ap.add_argument("--set", nargs="*", default=[], help="override settings, e.g. prices.scenario=high")
    a = ap.parse_args(argv)
    cfg = D.load_config(a.config, parse_sets(a.set))
    if a.mode == "pathway":
        m, info, res = run_pathway(cfg, integer=not a.lp)
        name = a.name or "pathway"
    else:
        m, info, res = run_year(cfg, a.year, a.non_fossil, integer=not a.lp)
        name = a.name or f"year_{a.year}"
    out = save(name, info, res, cfg)
    print(res["capacity_mw"].round(1).T.to_string())
    print(res["costs"].round(2).T.to_string())
    print(f"{info['status']}, gap {info['gap']}, {info['seconds']:.0f} s; checks: {checks.summary(res['checks'])}; -> {out}")


if __name__ == "__main__":
    main()
