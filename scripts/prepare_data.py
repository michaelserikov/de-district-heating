"""Copy the public inputs into data/raw as small CSV files (run once; the repository ships the result).

Sources: DWD Climate Data Center, hourly air temperature, station 01048 Dresden-Klotzsche (CC BY 4.0);
SMARD day-ahead price DE-LU (Bundesnetzagentur, CC BY 4.0), via the cache of de-power-market-ppa;
monthly gas (TTF) and EU ETS prices from de-power-market-ppa (World Bank, ECB, ICAP / EEX public series);
PyPSA technology-data v0.13.4 (Danish Energy Agency technology catalogues, CC BY 4.0).
"""
from pathlib import Path
import zipfile

import pandas as pd

HOME = Path.home()
RAW = Path(__file__).resolve().parents[1] / "data" / "raw"
G4 = HOME / "data_g4" / "raw"

z = zipfile.ZipFile(G4 / "stundenwerte_TU_01048_19730101_20251231_hist.zip")
name = [n for n in z.namelist() if n.startswith("produkt")][0]
t = pd.read_csv(z.open(name), sep=";", skipinitialspace=True)
t["time"] = pd.to_datetime(t.MESS_DATUM.astype(str), format="%Y%m%d%H")  # DWD hourly data are in UTC since 2000
t = t[(t.time >= "2015-01-01") & (t.time < "2026-01-01")]
t["t_air"] = t.TT_TU.where(t.TT_TU > -999)
t[["time", "t_air"]].to_csv(RAW / "dwd_01048_dresden_t_air_hourly.csv", index=False, float_format="%.1f")

p = pd.read_parquet(HOME / "de-power-market-ppa" / "data" / "hourly_raw.parquet")
p = p[["ts_utc", "price"]].rename(columns={"ts_utc": "time", "price": "da_price"})
p.to_csv(RAW / "smard_da_price_de_lu_hourly.csv", index=False)

f = pd.read_csv(HOME / "de-power-market-ppa" / "results" / "dispatch" / "fuel_prices_monthly.csv")
f[["month", "gas_eur_mwh", "co2_eur_t"]].to_csv(RAW / "fuel_prices_monthly.csv", index=False)

techs = ["central air-sourced heat pump", "central excess-heat-sourced heat pump", "central gas CHP", "central gas boiler",
         "central resistive heater", "solid biomass boiler steam", "central water tank storage", "central water pit storage",
         "gas", "solid biomass"]
rows = []
for y in (2025, 2030, 2035, 2040, 2045):
    c = pd.read_csv(G4 / "techdata" / f"costs_{y}.csv")
    c = c[c.technology.isin(techs)].assign(year=y)
    rows.append(c[["year", "technology", "parameter", "value", "unit", "source"]])
pd.concat(rows).to_csv(RAW / "technology_data_dea.csv", index=False)
print("ok")
