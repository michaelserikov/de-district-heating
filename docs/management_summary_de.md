# Fernwärmetransformation einer Beispielstadt: Ergebnisse auf einer Seite

**Fragestellung.** Mit welchem Erzeugungspark erfüllt ein Fernwärmenetz von rund 1 TWh Wärme pro Jahr die Vorgaben
des Wärmeplanungsgesetzes (30 % erneuerbare Wärme oder unvermeidbare Abwärme ab 2030, 80 % ab 2040, klimaneutral
2045) zu den geringsten Systemkosten, und welche Annahmen entscheiden darüber?

**Methode.** Python-basiertes Optimierungsmodell (LP/MILP, Pyomo mit HiGHS): Investitionen in den Stützjahren 2030,
2035, 2040 und 2045 und stündlicher Einsatz aller Anlagen. Reale Temperaturen (DWD Dresden-Klotzsche) und
Day-Ahead-Preise (SMARD) 2023 bis 2025, Technologiekosten nach dem Katalog der Danish Energy Agency. Netzgröße,
Bestandsanlagen und lokale Potenziale sind Annahmen eines Beispielnetzes, keine Daten eines Versorgers.

**Ergebnisse (zentrales Szenario).**
1. Zuerst die günstigen Quellen: Abwasser-Wärmepumpen (40 MW), Holzhackschnitzelkessel (30 MW, bis 2045 110 MW) und
   ein saisonaler Erdbeckenspeicher (3.000 MWh) bereits 2030. Damit wird die 30-%-Quote erreicht.
2. Nach dem Ausscheiden des Gas-BHKW folgen Luft-Wärmepumpen (70 MW 2040, 140 MW 2045). Für die letzten Prozent bis
   zur Klimaneutralität kommen ein Elektrokessel (70 MW) und ein Wärmespeicher (5.400 MWh) für Kälteperioden hinzu.
3. Die Wärmegestehungskosten des Systems steigen von 40 auf 60 EUR/MWh. Barwert der Systemkosten 2026 bis 2049: rund
   570 Mio. EUR.
4. Heute lohnt sich eine einzelne Großwärmepumpe im Bestand kaum: Sie läuft in den günstigen Stunden, senkt die
   Jahreskosten bei 45 EUR/MWh Netzentgelten und Umlagen aber höchstens um 0,7 Mio. EUR (2023), 2024 und 2025 gar
   nicht.

**Was die Kosten am stärksten bewegt.**

| Annahme | Barwert gegenüber zentral |
|---|---|
| Brennstoff-, CO2- und Strompreise hoch / niedrig | +154 / -105 Mio. EUR |
| BEW-Förderung (40 % Investition, Betriebskostenförderung Wärmepumpen) | -285 Mio. EUR |
| Netzentgelte und Umlagen auf Wärmepumpenstrom 70 / 20 EUR/MWh | +29 / -42 Mio. EUR |
| Netztemperaturen 10 K niedriger | -16 Mio. EUR |
| ohne Abwasserwärme / weniger Holz / ohne Erdbeckenspeicher | +8 bis +10 Mio. EUR |

**Einordnung für Entscheidungen.**
- Preis- und Förderrahmen wirken stärker als jede technische Einzelentscheidung; Investitionsentscheidungen sollten
  deshalb in mehreren Preisszenarien bestehen, nicht nur im zentralen.
- Die Stromnebenkosten entscheiden über die Aufteilung zwischen Wärmepumpe und Elektrokessel.
- Die Absenkung der Netztemperaturen ist der wirksamste technische Hebel im Modell.
- Die Ergebnisse bei 6-Stunden-Auflösung liegen 2 % über der stündlichen Rechnung; Spitzenanlagen (Elektrokessel)
  werden damit unterschätzt und sollten für die finale Variante stündlich nachgerechnet werden.

**Grenzen.** Beispielnetz mit angenommenen Potenzialen, ein Wetterjahr, künftige Strompreise mit dem Preisprofil von
2024, keine Mindestlasten und Anfahrkosten des BHKW, kein Wasserstoff oder Biomethan.
