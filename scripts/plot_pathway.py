"""Figure of the central MILP pathway: capacity and heat by technology per milestone year."""
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from fernwaerme import data as D

R = D.ROOT / "results" / "wp23" / "milp_central"
cap = pd.read_csv(R / "capacity_mw.csv", index_col=0)
en = pd.read_csv(R / "energy_gwh.csv", index_col=0)
cost = pd.read_csv(R / "costs.csv", index_col=0)
techs = ["gas_chp", "gas_boiler", "hp_sewage", "hp_air", "biomass", "e_boiler"]
colors = ["tab:orange", "tab:red", "tab:cyan", "tab:green", "tab:brown", "tab:purple"]
fig, axes = plt.subplots(1, 2, figsize=(11, 4))
x = [str(y) for y in en.index]
bottom = 0
for t, c in zip(techs, colors):
    axes[0].bar(x, en[t], bottom=bottom, color=c, label=t.replace("_", " "))
    bottom = bottom + en[t]
axes[0].set_ylabel("heat (GWh/a)")
axes[0].set_title("Heat by technology, central case (MILP)", fontsize=9)
axes[0].legend(fontsize=7)
for i, y in enumerate(en.index):
    axes[0].text(i, bottom.iloc[i] + 15, f"{en.non_fossil_share.iloc[i]:.0%} non-fossil", ha="center", fontsize=7)
ax = axes[1]
for t, c in zip(techs[2:], colors[2:]):
    ax.plot(x, cap[t], "o-", color=c, label=t.replace("_", " "))
ax.set_ylabel("capacity (MW heat)")
ax2 = ax.twinx()
ax2.plot(x, cost.heat_cost_eur_mwh, "k--", label="heat cost")
ax2.set_ylabel("system cost per MWh heat (EUR)")
ax.set_title("New capacity and heat cost", fontsize=9)
ax.legend(fontsize=7, loc="upper left")
fig.tight_layout()
fig.savefig(D.ROOT / "figures" / "wp2_pathway.png", dpi=140)
