# Epoch-összevetés — benchmark_raw_2026-08-11.json

| Mérőszám | szabi-8b-v13-e2 | szabi-8b-v13 | szabi-8b-v12 |
| :--- | ---: | ---: | ---: |
| koherencia-válasz átlaghossz (szó) | 27 | 26 | 20 |
| koherencia-válasz leghosszabb | 32 | 27 | 32 |
| köszönést viszonoz | 2/2 | 2/2 | 2/2 |
| megszólítás ('Teremtőm') | 11/25 = 44% | 13/25 = 52% | 10/25 = 40% |
| KITALÁLT tool-név ⬇ | 0 | 0 | 0 |
| ELVESZETT tool-blokk ⬇ | 0 | 0 | 0 |
| csupasz tool-hívás ⬇ | 3/7 | 2/5 | 2/4 |

## Olvasat

- A **koherencia-hossz** a v11 tétje: a 18 új példa 100–106 szavas. Ha egy
  oszlop itt a v10 szintjén marad, az a checkpoint nem tanulta meg az új adatot —
  és akkor NEM az epoch-szám a hibás, hanem az adat nem jutott el hozzá.
- A **kitalált tool-név** és a **csupasz tool-hívás** a romlás-őrök: ha ezek nőnek,
  a hosszabb tanítás mást rontott el. Ilyenkor a kisebb epoch-szám nyer.
- Ez a tábla a MECHANIZMUST méri, nem a minőséget. A 'vállalható-e a demóra'
  kérdésre a vak, bináris aréna válaszol (run_benchmark.py --anchor + --decode).
EXIT=0
