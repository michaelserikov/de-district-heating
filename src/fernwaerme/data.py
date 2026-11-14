"""Inputs: configuration, heat demand, heat-pump COP, prices and technology data."""
from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
CONFIG = ROOT / "config" / "base.yaml"


def load_config(path: Path | str = CONFIG, overrides: dict | None = None) -> dict:
    cfg = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    for key, val in (overrides or {}).items():
        set_key(cfg, key, val)
    return cfg


def set_key(cfg: dict, dotted: str, value):
    node = cfg
    parts = dotted.split(".")
    for p in parts[:-1]:
        node = node[p]
    if parts[-1] not in node:
        raise KeyError(f"unknown setting {dotted}")
    node[parts[-1]] = value


def with_overrides(cfg: dict, **dotted) -> dict:
    out = copy.deepcopy(cfg)
    for k, v in dotted.items():
        set_key(out, k.replace("__", "."), v)
    return out


# ---------------------------------------------------------------- weather and prices
def temperature(year: int) -> pd.Series:
    t = pd.read_csv(RAW / "dwd_01048_dresden_t_air_hourly.csv", parse_dates=["time"]).set_index("time").t_air
    t = t[str(year)]
    idx = pd.date_range(f"{year}-01-01", f"{year}-12-31 23:00", freq="h")
    t = t[~t.index.duplicated()].reindex(idx)
    return t.interpolate(limit=6).ffill().bfill()


def day_ahead_price(year: int) -> pd.Series:
    p = pd.read_csv(RAW / "smard_da_price_de_lu_hourly.csv")
    p.index = pd.to_datetime(p.time, utc=True).dt.tz_localize(None)
    p = p.da_price[str(year)]
    idx = pd.date_range(f"{year}-01-01", f"{year}-12-31 23:00", freq="h")
    return p[~p.index.duplicated()].reindex(idx).interpolate().ffill().bfill()


def fuel_prices(year: int) -> dict:
    f = pd.read_csv(RAW / "fuel_prices_monthly.csv")
    f = f[f.month.str.startswith(str(year))]
    return {"gas": float(f.gas_eur_mwh.mean()), "co2": float(f.co2_eur_t.mean())}


# ---------------------------------------------------------------- demand and COP
def _space_heat_index(t_air: pd.Series, cfg: dict) -> np.ndarray:
    d = cfg["demand"]
    daily = t_air.resample("D").mean()
    t_eff = sum(wi * daily.shift(i).bfill() for i, wi in enumerate(d["smoothing"]))
    hdd = (d["heating_limit_c"] - t_eff).clip(lower=0)
    return hdd.reindex(t_air.index.normalize()).to_numpy() * _day_shape(t_air.index, cfg)


def _day_shape(hours: pd.DatetimeIndex, cfg: dict) -> np.ndarray:
    d = cfg["demand"]
    shape = np.where((hours.hour >= 6) & (hours.hour < 21), d["day_factor"], d["night_factor"])
    return shape / (15 * d["day_factor"] + 9 * d["night_factor"]) * 24


def heat_demand(t_air: pd.Series, cfg: dict, ref_t_air: pd.Series | None = None) -> pd.Series:
    """Hourly heat fed into the network (MW). Scaled so that the reference weather year (default: the same year)
    sums to the configured annual total; another year then differs only through its weather."""
    d = cfg["demand"]
    ref = t_air if ref_t_air is None else ref_t_air
    total = d["annual_gwh"] * 1000.0
    k_space = total * (1 - d["hot_water_share"] - d["loss_share"]) / _space_heat_index(ref, cfg).sum()
    hours = t_air.index
    space = _space_heat_index(t_air, cfg) * k_space
    hot = _day_shape(hours, cfg) * total * d["hot_water_share"] / len(ref)
    loss = np.full(len(hours), total * d["loss_share"] / len(ref))
    return pd.Series(space + hot + loss, index=hours, name="heat_demand_mw")


def supply_temperature(t_air: pd.Series, cfg: dict) -> pd.Series:
    n = cfg["network_temperature"]
    frac = ((t_air - n["t_cold_c"]) / (n["t_warm_c"] - n["t_cold_c"])).clip(0, 1)
    return n["supply_cold_c"] + frac * (n["supply_warm_c"] - n["supply_cold_c"])


def lorenz_cop(t_source: np.ndarray, t_supply: np.ndarray, t_return: float, quality: float, approach: float,
               source_drop: float = 4.0) -> np.ndarray:
    """COP from the Lorenz (log-mean temperature) cycle: the network water is heated from return to supply
    temperature, the source is cooled by `source_drop` K; `quality` is the share of the ideal COP reached."""
    sup = np.asarray(t_supply) + approach + 273.15
    ret = t_return + approach + 273.15
    hot = (sup - ret) / np.log(sup / ret)
    s_in = np.asarray(t_source) - approach + 273.15
    s_out = s_in - source_drop
    cold = (s_in - s_out) / np.log(s_in / s_out)
    return np.clip(quality * hot / np.maximum(hot - cold, 1.0), 1.0, 8.0)


def cops(t_air: pd.Series, cfg: dict) -> pd.DataFrame:
    c = cfg["cop"]
    sink = supply_temperature(t_air, cfg).to_numpy()
    doy = t_air.index.dayofyear.to_numpy()
    sewage = c["sewage_mean_c"] + c["sewage_amplitude_c"] * np.cos(2 * np.pi * (doy - 227) / 365.25)
    return pd.DataFrame({
        "hp_air": lorenz_cop(t_air.to_numpy(), sink, cfg["network_temperature"]["return_c"], c["lorenz_quality"], c["approach_k"]),
        "hp_sewage": lorenz_cop(sewage, sink, cfg["network_temperature"]["return_c"], c["lorenz_quality"], c["approach_k"]),
    }, index=t_air.index)


# ---------------------------------------------------------------- technologies
TECH_MAP = {
    "hp_air": "central air-sourced heat pump",
    "hp_sewage": "central excess-heat-sourced heat pump",
    "gas_chp": "central gas CHP",
    "gas_boiler": "central gas boiler",
    "e_boiler": "central resistive heater",
    "biomass": "solid biomass boiler steam",
    "tank": "central water tank storage",
    "pit": "central water pit storage",
}


@dataclass
class Tech:
    capex: float      # EUR per MW heat (or per MWh for storage)
    fom: float        # share of capex per year
    vom: float        # EUR per MWh heat
    eff: float        # heat (or electricity for CHP) per unit fuel; 1 for storage
    life: float
    loss: float = 0.0     # storage standing loss per hour
    e2p: float = 0.0      # storage energy-to-power ratio (h)


def technologies(year: int) -> dict[str, Tech]:
    d = pd.read_csv(RAW / "technology_data_dea.csv")
    yrs = sorted(d.year.unique())
    y = min(yrs, key=lambda v: abs(v - year))
    d = d[d.year == y]

    def g(tech, par, default=0.0):
        r = d[(d.technology == TECH_MAP[tech]) & (d.parameter == par)]
        return float(r.value.iloc[0]) if len(r) else default

    out = {}
    for k in TECH_MAP:
        inv = g(k, "investment") * 1000.0          # per kW -> per MW (per kWh -> per MWh for storage)
        out[k] = Tech(capex=inv, fom=g(k, "FOM") / 100.0, vom=g(k, "VOM"), eff=g(k, "efficiency", 1.0),
                      life=g(k, "lifetime", 25.0), loss=g(k, "standing losses") / 100.0, e2p=g(k, "energy to power ratio"))
    return out


def annuity(rate: float, life: float) -> float:
    return rate / (1 - (1 + rate) ** -life)


def emission_factor_gas() -> float:
    d = pd.read_csv(RAW / "technology_data_dea.csv")
    r = d[(d.technology == "gas") & (d.parameter == "CO2 intensity")]
    return float(r.value.iloc[0])


def aggregate(df: pd.DataFrame | pd.Series, step: int, how: str = "mean"):
    """Average consecutive hours into blocks of `step` hours (prices, demand, COP)."""
    if step == 1:
        return df
    g = np.arange(len(df)) // step
    out = df.groupby(g).mean() if how == "mean" else df.groupby(g).sum()
    out.index = df.index[::step][: len(out)]
    return out
