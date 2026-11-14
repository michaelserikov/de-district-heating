"""Data and model quality checks: inputs before the solve, energy balances and limits after it.

Each check returns a row (name, value, limit, ok). A failed input check raises before the solver starts, because a
solver result on bad data looks just as plausible as a good one. Solution checks are reported, not raised, so a
run with unserved heat still shows when and how much heat is missing.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pyomo.environ as pyo


class InputError(ValueError):
    pass


def check_inputs(cfg: dict, years) -> pd.DataFrame:
    rows = []
    for y in years:
        d = y.demand.to_numpy()
        rows += [
            (y.year, "demand has no gaps", int(np.isnan(d).sum()), 0, not np.isnan(d).any()),
            (y.year, "demand non-negative", float(d.min()), 0.0, d.min() >= 0),
            (y.year, "annual demand within 15% of config (GWh, other weather years differ)", float(d.sum() * cfg["step_hours"] / 1000),
             cfg["demand"]["annual_gwh"], abs(d.sum() * cfg["step_hours"] / 1000 / cfg["demand"]["annual_gwh"] - 1) < 0.15),
            (y.year, "COP in 1-8", float(y.cop.to_numpy().min()), 1.0, bool(((y.cop >= 1) & (y.cop <= 8)).all().all())),
            (y.year, "power price finite", float(np.isfinite(y.power).mean()), 1.0, bool(np.isfinite(y.power).all())),
            (y.year, "share target in [0,1]", y.non_fossil, 1.0, 0 <= y.non_fossil <= 1),
        ]
    shares = [y.non_fossil for y in years]
    rows.append(("all", "share targets do not fall", min(np.diff(shares)) if len(shares) > 1 else 0, 0,
                 all(np.diff(shares) >= 0)))
    df = pd.DataFrame(rows, columns=["year", "check", "value", "limit", "ok"])
    if not df.ok.all():
        raise InputError("input checks failed:\n" + df[~df.ok].to_string(index=False))
    return df


def check_solution(m, cfg: dict, tol: float = 1e-3) -> pd.DataFrame:
    from .model import NON_FOSSIL, PRODUCERS, STORES
    rows = []
    h = m._step
    for i in m.Y:
        y = m._years[i]
        dem = y.demand.to_numpy()[: m._nT]
        q = np.array([[pyo.value(m.q[k, i, t]) for t in m.T] for k in PRODUCERS])
        ch = np.array([[pyo.value(m.ch[s, i, t]) for t in m.T] for s in STORES])
        dis = np.array([[pyo.value(m.dis[s, i, t]) for t in m.T] for s in STORES])
        soc = np.array([[pyo.value(m.soc[s, i, t]) for t in m.T] for s in STORES])
        uns = np.array([pyo.value(m.unserved[i, t]) for t in m.T])
        resid = q.sum(0) + dis.sum(0) - ch.sum(0) + uns - dem
        caps = np.array([pyo.value(m.cap[k, i]) for k in PRODUCERS])
        scap = np.array([pyo.value(m.cap[s, i]) for s in STORES])
        share = q[[PRODUCERS.index(k) for k in NON_FOSSIL]].sum() / max(q.sum(), 1e-9)
        both = np.minimum(ch, dis).max() if ch.size else 0.0
        rows += [
            (y.year, "energy balance residual (MW, max)", float(np.abs(resid).max()), tol, np.abs(resid).max() <= tol),
            (y.year, "output within capacity (MW, max excess)", float((q - caps[:, None]).max()), tol,
             (q - caps[:, None]).max() <= tol),
            (y.year, "storage level within capacity", float((soc - scap[:, None]).max()), tol, (soc - scap[:, None]).max() <= tol),
            (y.year, "unserved heat (GWh)", float(uns.sum() * h / 1000), 0.0, uns.sum() * h <= 1.0),
            (y.year, "unserved hours", int((uns > tol).sum() * h), 0, (uns > tol).sum() == 0),
            (y.year, "non-fossil share reached", float(share), y.non_fossil, share >= y.non_fossil - 1e-4),
            (y.year, "simultaneous charge and discharge (MW, max)", float(both), tol, both <= tol),
        ]
    return pd.DataFrame(rows, columns=["year", "check", "value", "limit", "ok"])


def summary(df: pd.DataFrame) -> str:
    bad = df[~df.ok]
    if bad.empty:
        return f"all {len(df)} passed"
    return f"{len(bad)} of {len(df)} failed: " + "; ".join(f"{r.year} {r.check} = {r.value:.3g}" for r in bad.itertuples())
