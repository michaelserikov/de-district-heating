"""Investment and dispatch model of a district heating system (Pyomo, solved with HiGHS).

One model covers one or several milestone years. Each year has its own time series (heat demand, heat-pump COP,
day-ahead power price) and price levels; capacity built in a year stays available in later years. New heat pumps,
biomass boilers and electric boilers come in modules (integer variables) unless the module size is 0 or the model
is built as an LP relaxation. Demand is met in every time step; a priced slack (unserved heat) keeps the model
feasible and shows where an input set cannot meet demand.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
import pyomo.environ as pyo
from pyomo.contrib.appsi.solvers import Highs

from . import data as D

PRODUCERS = ["gas_chp", "gas_boiler", "hp_air", "hp_sewage", "biomass", "e_boiler"]
NEW = ["hp_air", "hp_sewage", "biomass", "e_boiler", "gas_boiler", "tank", "pit"]
STORES = ["tank", "pit"]
NON_FOSSIL = ["hp_air", "hp_sewage", "biomass", "e_boiler"]
FOSSIL = ["gas_chp", "gas_boiler"]


@dataclass
class YearInput:
    year: int
    demand: pd.Series            # MW per step
    cop: pd.DataFrame            # hp_air, hp_sewage
    power: pd.Series             # EUR/MWh day-ahead
    gas: float                   # EUR/MWh fuel
    co2: float                   # EUR/t
    non_fossil: float            # minimum share of heat from non-fossil sources
    chp_available: bool
    techs: dict = field(default_factory=dict)


def year_inputs(cfg: dict, years: list[int], shares: list[float] | None = None, scenario: str | None = None) -> list[YearInput]:
    """Build inputs for milestone years from the weather year and the price scenario."""
    wy = cfg["weather_year"]
    step = cfg["step_hours"]
    t_ref = D.temperature(wy)
    scen = cfg["price_scenarios"][scenario or cfg["prices"]["scenario"]]
    path_years = cfg["pathway"]["years"]
    out = []
    for i, y in enumerate(years):
        j = path_years.index(y) if y in path_years else None
        if j is None:  # a historical year: its own weather, day-ahead prices and fuel prices
            t = D.temperature(y)
            da = D.day_ahead_price(y)
            fp = D.fuel_prices(y)
            gas, co2, power = fp["gas"], fp["co2"], da
        else:  # a milestone year: weather-year hours, scenario price levels
            t = t_ref
            da = D.day_ahead_price(wy)
            gas, co2 = scen["gas"][j], scen["co2"][j]
            power = da - da.mean() + scen["power"][j]
        demand = D.heat_demand(t, cfg, ref_t_air=t_ref)
        cop = D.cops(t, cfg)
        inv_cop = 1.0 / cop
        out.append(YearInput(
            year=y,
            demand=D.aggregate(demand, step),
            cop=1.0 / D.aggregate(inv_cop, step),      # average electricity per heat within a block
            power=D.aggregate(power, step),
            gas=gas, co2=co2,
            non_fossil=(shares[i] if shares is not None else 0.0),
            chp_available=y <= cfg["pathway"]["chp_retire_after"],
            techs=D.technologies(y),
        ))
    return out


def build(cfg: dict, years: list[YearInput], integer: bool = True, fixed_builds: dict | None = None,
          base_year: int = 2026) -> pyo.ConcreteModel:
    step = cfg["step_hours"]
    r = cfg["discount_rate"]
    period = cfg["pathway"]["period_years"] if len(years) > 1 else 1
    pr = cfg["prices"]
    sub = cfg["subsidy"]
    ex = cfg["existing"]
    ef = D.emission_factor_gas()

    m = pyo.ConcreteModel()
    m.Y = pyo.Set(initialize=range(len(years)), ordered=True)
    nT = min(len(y.demand) for y in years)
    m.T = pyo.Set(initialize=range(nT), ordered=True)
    m.P = pyo.Set(initialize=PRODUCERS)
    m.N = pyo.Set(initialize=NEW)
    m.S = pyo.Set(initialize=STORES)

    # investments
    mod = cfg["new_units"]
    m.n = pyo.Var(m.N, m.Y, domain=pyo.NonNegativeIntegers if integer else pyo.NonNegativeReals)
    m.b = pyo.Var(m.N, m.Y, domain=pyo.NonNegativeReals)
    m.module = pyo.ConstraintList()
    for k in NEW:
        for i in m.Y:
            size = mod.get(k, 0)
            if size and integer:
                m.module.add(m.b[k, i] == size * m.n[k, i])
            else:
                m.n[k, i].fix(0)
            if fixed_builds is not None:
                m.b[k, i].fix(fixed_builds.get(k, [0] * len(years))[i])

    def cap(k, i):
        built = sum(m.b[k, j] for j in m.Y if j <= i) if k in NEW else 0
        if k == "gas_chp":
            return ex["gas_chp"] if years[i].chp_available else 0.0
        if k == "gas_boiler":
            return ex["gas_boiler"] + built
        if k == "tank":
            return ex["tank"] + built
        return built

    m.cap = pyo.Expression(list(PRODUCERS) + STORES, m.Y, rule=lambda m, k, i: cap(k, i))
    m.pit_limit = pyo.Constraint(m.Y, rule=lambda m, i: m.cap["pit", i] <= cfg["limits"]["pit_max_mwh"])
    m.sewage_limit = pyo.Constraint(m.Y, rule=lambda m, i: m.cap["hp_sewage", i] <= cfg["cop"]["sewage_potential_mw"])

    # dispatch
    m.q = pyo.Var(m.P, m.Y, m.T, domain=pyo.NonNegativeReals)
    m.ch = pyo.Var(m.S, m.Y, m.T, domain=pyo.NonNegativeReals)
    m.dis = pyo.Var(m.S, m.Y, m.T, domain=pyo.NonNegativeReals)
    m.soc = pyo.Var(m.S, m.Y, m.T, domain=pyo.NonNegativeReals)
    m.unserved = pyo.Var(m.Y, m.T, domain=pyo.NonNegativeReals)

    dem = {i: years[i].demand.to_numpy() for i in m.Y}
    copv = {i: years[i].cop.to_numpy() for i in m.Y}
    pw = {i: years[i].power.to_numpy() for i in m.Y}
    tech = {i: years[i].techs for i in m.Y}

    m.cap_limit = pyo.Constraint(m.P, m.Y, m.T, rule=lambda m, k, i, t: m.q[k, i, t] <= m.cap[k, i])
    m.balance = pyo.Constraint(m.Y, m.T, rule=lambda m, i, t: sum(m.q[k, i, t] for k in m.P)
                               + sum(m.dis[s, i, t] - m.ch[s, i, t] for s in m.S) + m.unserved[i, t] == float(dem[i][t]))

    def soc_rule(m, s, i, t):
        keep = (1 - tech[i][s].loss) ** step
        prev = m.soc[s, i, m.T.last()] if t == m.T.first() else m.soc[s, i, t - 1]  # cyclic within the year
        return m.soc[s, i, t] == keep * prev + step * (m.ch[s, i, t] - m.dis[s, i, t])

    m.soc_dyn = pyo.Constraint(m.S, m.Y, m.T, rule=soc_rule)
    m.soc_cap = pyo.Constraint(m.S, m.Y, m.T, rule=lambda m, s, i, t: m.soc[s, i, t] <= m.cap[s, i])
    # charging and discharging share the same diffusers and pumps: their sum is limited by the store's power
    m.flow_cap = pyo.Constraint(m.S, m.Y, m.T, rule=lambda m, s, i, t: (m.ch[s, i, t] + m.dis[s, i, t]) * tech[i][s].e2p
                                <= m.cap[s, i])

    m.biomass_limit = pyo.Constraint(m.Y, rule=lambda m, i: sum(m.q["biomass", i, t] for t in m.T) * step
                                     / tech[i]["biomass"].eff <= pr["biomass_limit_gwh"] * 1000.0)
    m.non_fossil = pyo.Constraint(m.Y, rule=lambda m, i: sum(m.q[k, i, t] for k in NON_FOSSIL for t in m.T)
                                  >= years[i].non_fossil * sum(m.q[k, i, t] for k in PRODUCERS for t in m.T))

    # costs (EUR per year of each milestone)
    def annual_cost(m, i):
        y = years[i]
        tk = tech[i]
        h = step
        gas_cost = y.gas + y.co2 * ef
        chp_el = sum(m.q["gas_chp", i, t] for t in m.T) * h * 1.0           # back-pressure, power = heat
        chp_fuel = chp_el / tk["gas_chp"].eff
        chp_rev = sum(m.q["gas_chp", i, t] * float(pw[i][t]) for t in m.T) * h + chp_el * pr["chp_bonus_eur_mwh"]
        boiler_fuel = sum(m.q["gas_boiler", i, t] for t in m.T) * h / tk["gas_boiler"].eff
        el_price = {t: float(pw[i][t]) + pr["grid_charges_eur_mwh"] for t in m.T}
        hp_el = sum((m.q["hp_air", i, t] / float(copv[i][t, 0]) + m.q["hp_sewage", i, t] / float(copv[i][t, 1]))
                    * el_price[t] for t in m.T) * h
        eb_el = sum(m.q["e_boiler", i, t] * el_price[t] for t in m.T) * h / tk["e_boiler"].eff
        bio = sum(m.q["biomass", i, t] for t in m.T) * h / tk["biomass"].eff * pr["biomass_eur_mwh"]
        vom = sum(tk[k].vom * sum(m.q[k, i, t] for t in m.T) * h for k in PRODUCERS)
        vom += cfg["storage_pumping_eur_mwh"] * sum(m.dis[s, i, t] for s in m.S for t in m.T) * h  # also removes degenerate charge+discharge
        hp_support = sub["bew_hp_operating_eur_mwh"] * sum(m.q[k, i, t] for k in ("hp_air", "hp_sewage") for t in m.T) * h
        fixed = sum(tk[k].fom * tk[k].capex * m.cap[k, i] for k in list(PRODUCERS) + STORES)
        capex = sum(m.b[k, j] * tech[j][k].capex * (1 - sub["bew_invest_share"]) * D.annuity(r, tech[j][k].life)
                    for k in NEW for j in m.Y if j <= i)
        unserved = sum(m.unserved[i, t] for t in m.T) * h * cfg["unserved_penalty_eur_mwh"]
        scale = 8760.0 / (nT * h)  # leap years and blocks
        return (scale * (chp_fuel * gas_cost - chp_rev + boiler_fuel * gas_cost + hp_el + eb_el + bio + vom
                         - hp_support + unserved) + fixed + capex)

    m.annual = pyo.Expression(m.Y, rule=annual_cost)
    disc = {i: period * (1 + r) ** -(years[i].year - base_year) for i in m.Y}
    m.obj = pyo.Objective(expr=sum(disc[i] * m.annual[i] for i in m.Y) / 1e3, sense=pyo.minimize)  # kEUR: well scaled for HiGHS
    m._years = years
    m._disc = disc
    m._step = step
    m._nT = nT
    return m


def solve(m: pyo.ConcreteModel, mip_gap: float = 0.005, time_limit: float = 600, tee: bool = False,
          method: str = "choose") -> dict:
    opt = Highs()
    opt.highs_options = {"solver": method}
    opt.config.mip_gap = mip_gap
    opt.config.time_limit = time_limit
    opt.config.load_solution = False
    opt.config.stream_solver = tee
    t0 = time.perf_counter()
    res = opt.solve(m)
    dt = time.perf_counter() - t0
    status = str(res.termination_condition).split(".")[-1]
    if res.best_feasible_objective is not None:
        res.solution_loader.load_vars()
    bound = res.best_objective_bound
    obj = res.best_feasible_objective
    gap = abs(obj - bound) / max(abs(obj), 1e-9) if (obj is not None and bound is not None) else None
    return {"status": status, "objective": obj, "bound": bound, "gap": gap, "seconds": dt}


def results(m: pyo.ConcreteModel) -> dict[str, pd.DataFrame]:
    years = m._years
    h = m._step
    scale = {i: 8760.0 / (m._nT * h) for i in m.Y}
    caps, energy, costs, builds = [], [], [], []
    for i in m.Y:
        y = years[i].year
        caps.append({"year": y, **{k: pyo.value(m.cap[k, i]) for k in list(PRODUCERS) + STORES}})
        builds.append({"year": y, **{k: pyo.value(m.b[k, i]) for k in NEW}})
        e = {k: sum(pyo.value(m.q[k, i, t]) for t in m.T) * h * scale[i] / 1000.0 for k in PRODUCERS}
        e["storage_out"] = sum(pyo.value(m.dis[s, i, t]) for s in m.S for t in m.T) * h * scale[i] / 1000.0
        e["unserved"] = sum(pyo.value(m.unserved[i, t]) for t in m.T) * h * scale[i] / 1000.0
        e["demand"] = float(years[i].demand.to_numpy()[: m._nT].sum()) * h * scale[i] / 1000.0
        e["non_fossil_share"] = sum(e[k] for k in NON_FOSSIL) / sum(e[k] for k in PRODUCERS)
        energy.append({"year": y, **e})
        costs.append({"year": y, "annual_cost_meur": pyo.value(m.annual[i]) / 1e6,
                      "heat_cost_eur_mwh": pyo.value(m.annual[i]) / (e["demand"] * 1000.0)})
    return {"capacity_mw": pd.DataFrame(caps).set_index("year"), "builds": pd.DataFrame(builds).set_index("year"),
            "energy_gwh": pd.DataFrame(energy).set_index("year"), "costs": pd.DataFrame(costs).set_index("year"),
            "npv_meur": pd.DataFrame({"npv_meur": [pyo.value(m.obj) / 1e3]})}


def dispatch_frame(m: pyo.ConcreteModel, i: int = 0) -> pd.DataFrame:
    y = m._years[i]
    idx = y.demand.index[: m._nT]
    cols = {k: [pyo.value(m.q[k, i, t]) for t in m.T] for k in PRODUCERS}
    for s in STORES:
        cols[f"{s}_out"] = [pyo.value(m.dis[s, i, t]) - pyo.value(m.ch[s, i, t]) for t in m.T]
        cols[f"{s}_soc"] = [pyo.value(m.soc[s, i, t]) for t in m.T]
    cols["unserved"] = [pyo.value(m.unserved[i, t]) for t in m.T]
    df = pd.DataFrame(cols, index=idx)
    df["demand"] = y.demand.to_numpy()[: m._nT]
    df["power_price"] = y.power.to_numpy()[: m._nT]
    df["cop_air"] = y.cop.hp_air.to_numpy()[: m._nT]
    return df
