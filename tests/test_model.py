"""Offline tests on small synthetic inputs (no data files needed except the configuration)."""
import numpy as np
import pandas as pd
import pytest

from fernwaerme import checks, data as D, model as M


def tech():
    t = {
        "hp_air": D.Tech(900e3, 0.002, 2.5, 3.0, 25),
        "hp_sewage": D.Tech(600e3, 0.003, 2.0, 1.0, 25),
        "gas_chp": D.Tech(600e3, 0.03, 4.4, 0.41, 25),
        "gas_boiler": D.Tech(50e3, 0.04, 1.0, 1.04, 25),
        "e_boiler": D.Tech(60e3, 0.02, 1.0, 0.99, 20),
        "biomass": D.Tech(600e3, 0.06, 2.8, 0.89, 25),
        "tank": D.Tech(3e3, 0.01, 0.0, 1.0, 40, loss=0.0001, e2p=60),
        "pit": D.Tech(1e3, 0.002, 0.0, 1.0, 30, loss=0.0001, e2p=30),
    }
    return t


def cfg(**over):
    c = D.load_config()
    c["step_hours"] = 1
    c["cop"]["sewage_potential_mw"] = 0
    for k, v in over.items():
        D.set_key(c, k.replace("__", "."), v)
    return c


def year(n=48, demand=100.0, price=None, share=0.0, cop=3.0, chp=True, y=2030):
    idx = pd.date_range("2030-01-01", periods=n, freq="h")
    price = np.full(n, 80.0) if price is None else np.asarray(price, float)
    return M.YearInput(year=y, demand=pd.Series(demand, index=idx), cop=pd.DataFrame({"hp_air": cop, "hp_sewage": cop}, index=idx),
                       power=pd.Series(price, index=idx), gas=30.0, co2=100.0, non_fossil=share, chp_available=chp, techs=tech())


def test_balance_and_checks_pass():
    c = cfg()
    m = M.build(c, [year()], integer=False)
    info = M.solve(m)
    assert info["status"] == "optimal"
    chk = checks.check_solution(m, c)
    assert chk.ok.all(), chk[~chk.ok]


def test_non_fossil_target_forces_heat_pumps():
    c = cfg()
    m = M.build(c, [year(share=0.8)], integer=False)
    M.solve(m)
    r = M.results(m)
    e = r["energy_gwh"].iloc[0]
    assert e.non_fossil_share >= 0.8 - 1e-6
    assert r["capacity_mw"].iloc[0][["hp_air", "e_boiler", "biomass"]].sum() > 0


def test_modules_are_integer_multiples():
    c = cfg()
    m = M.build(c, [year(share=0.5)], integer=True)
    M.solve(m)
    b = M.results(m)["builds"].iloc[0]
    assert abs(b.hp_air / c["new_units"]["hp_air"] - round(b.hp_air / c["new_units"]["hp_air"])) < 1e-6


def test_chp_runs_when_power_is_expensive():
    c = cfg()
    price = np.r_[np.full(24, 20.0), np.full(24, 300.0)]
    m = M.build(c, [year(price=price)], integer=False)
    M.solve(m)
    d = M.dispatch_frame(m)
    assert d.gas_chp.iloc[24:].mean() > d.gas_chp.iloc[:24].mean()


def test_unserved_heat_is_reported_not_infeasible():
    c = cfg(existing__gas_boiler=0, existing__gas_chp=0, prices__biomass_limit_gwh=0, unserved_penalty_eur_mwh=1.0)
    c["new_units"] = {k: 0 for k in c["new_units"]}
    m = M.build(c, [year(share=0.0)], integer=False)
    for k in M.NEW:   # nothing may be built either
        m.b[k, 0].fix(0)
    info = M.solve(m)
    assert info["status"] == "optimal"
    chk = checks.check_solution(m, c)
    assert not chk.set_index("check").loc["unserved heat (GWh)", "ok"]


def test_input_check_rejects_negative_demand():
    c = cfg()
    y = year()
    y.demand.iloc[3] = -5
    with pytest.raises(checks.InputError):
        checks.check_inputs(c | {"demand": {**c["demand"], "annual_gwh": y.demand.sum() / 1000}}, [y])


def test_lorenz_cop_rises_with_source_temperature():
    lo = D.lorenz_cop(np.array([-5.0]), np.array([80.0]), 45.0, 0.5, 3.0)
    hi = D.lorenz_cop(np.array([15.0]), np.array([80.0]), 45.0, 0.5, 3.0)
    assert hi > lo > 1


def test_annuity():
    assert D.annuity(0.05, 20) == pytest.approx(0.0802426, rel=1e-5)


def test_no_simultaneous_charge_discharge_with_negative_prices():
    c = cfg()
    price = np.tile(np.r_[np.full(6, -40.0), np.full(18, 120.0)], 2)
    m = M.build(c, [year(price=price, share=1.0, demand=np.r_[np.full(24, 60.0), np.full(24, 140.0)])], integer=False)
    M.solve(m)
    chk = checks.check_solution(m, c).set_index("check")
    assert chk.loc["simultaneous charge and discharge (MW, max)", "ok"]
