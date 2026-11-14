# User guide

For colleagues who want to run a variant without reading the code.

## Install

```
python -m venv .venv
.venv/Scripts/activate          # Linux/macOS: source .venv/bin/activate
pip install -e ".[test]"
pytest -q                       # 8 tests, synthetic inputs, about 5 seconds
```

HiGHS comes with the `highspy` package; no commercial solver is needed.

## Where the assumptions are

Every assumption is in `config/base.yaml`, with a comment giving its source or the reasoning behind it. Nothing
numerical is hidden in the code except the physical constants of the COP formula. Technology costs come from
`data/raw/technology_data_dea.csv` (Danish Energy Agency values via PyPSA technology-data, by year).

When an assumption is agreed with a department, change it in `base.yaml` and commit the change, so that every
result can be traced to the assumptions it was computed with. Each run also writes `config_used.yaml` next to
its results.

## Run a variant

```
cd src
python -m fernwaerme.run pathway --name central
python -m fernwaerme.run pathway --name grid_fees_70 --set prices.grid_charges_eur_mwh=70
python -m fernwaerme.run pathway --name bew --set subsidy.bew_invest_share=0.4 subsidy.bew_hp_operating_eur_mwh=30
python -m fernwaerme.run pathway --name fast --lp --set step_hours=6
python -m fernwaerme.run year --year 2024 --set step_hours=1
```

`--set` takes any key of `base.yaml` in dotted form; an unknown key stops the run with an error rather than being
ignored. `--lp` relaxes the module sizes (faster, sizes continuous). Results are written to `results/<name>/`:

| file | content |
|---|---|
| `capacity_mw.csv` | capacity per technology and milestone year (MW heat, MWh for storage) |
| `builds.csv` | new capacity built in each milestone year |
| `energy_gwh.csv` | heat per technology, unserved heat, non-fossil share |
| `costs.csv` | annual system cost and cost per MWh of heat |
| `checks.csv` | balance, capacity, storage, target and unserved-heat checks after the solve |
| `solve.json` | solver status, MIP gap, run time |

## When a run looks wrong

1. **Input checks stop the run** (`InputError`): the message names the year and the check, for example a gap in
   the demand series or a target that falls between milestone years. Fix the input, not the check.
2. **`checks.csv` shows unserved heat**: the run did not fail, demand could not be met with the allowed options.
   `scripts/wp4_quality.py` shows how to read when and how much heat is missing (for example: too little
   heat-pump capacity for cold spells). Unserved heat costs 10,000 EUR/MWh, so it appears only when nothing else
   is possible.
3. **Slow MILP**: run with `--lp` first. The gap between LP and MILP cost is small here (see WP4), so the LP
   is a good guide to which variants matter before running the MILP.
4. **Time resolution**: 6-hour steps are about 2% cheaper than hourly and undersize peak units; check the
   final variant at 1 or 3 hours.
