# Tool-megbízhatóság — 3 futás/kérdés, változó seed (42..44)

| Kérdés | típus | szabi-3b-v7 | szabi-3b-v8 | szabi-3b-v9 | szabi-3b-v10 | szabi-3b-v11e1 | szabi-3b-v11e2 | szabi-3b-v11e3 | llama3.2:3b |
| :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| tc_01 | mem | 0 | 0 | 0 | 0 | 1 | 2 | 2 | 0 |
| tc_02 | új | 2 | 0 | 2 | 0 | 0 | 2 | 1 | 0 |
| tc_03 | mem | 2 | 3 | 2 | 1 | 2 | 3 | 3 | 0 |
| tc_04 | mem | 0 | 1 | 2 | 0 | 0 | 0 | 1 | 0 |
| tc_05 | új | 0 | 2 | 0 | 1 | 1 | 2 | 1 | 0 |
| tn_01 | új | 3 | 2 | 0 | 0 | 1 | 3 | 3 | 0 |
| tn_02 | új | 0 | 0 | 0 | 0 | 1 | 0 | 2 | 0 |
| tn_03 | új | 0 | 0 | 0 | 1 | 0 | 1 | 1 | 0 |
| tn_04 | neg | 2 | 0 | 2 | 1 | 1 | 2 | 1 | 3 |
| tn_05 | neg | 2 | 3 | 3 | 3 | 2 | 2 | 3 | 3 |

| ÖSSZESEN | | **11/30** (37%) | **11/30** (37%) | **11/30** (37%) | **7/30** (23%) | **9/30** (30%) | **17/30** (57%) | **18/30** (60%) | **6/30** (20%) |
|   ebből pozitív | | 7/24 | 8/24 | 6/24 | 3/24 | 6/24 | 13/24 | 14/24 | 0/24 |
|   ebből negatív | | 4/6 | 3/6 | 5/6 | 4/6 | 3/6 | 4/6 | 4/6 | 6/6 |
|   ebből memorizált | | 2/9 | 4/9 | 4/9 | 1/9 | 3/9 | 5/9 | 6/9 | 0/9 |
|   ebből új | | 9/21 | 7/21 | 7/21 | 6/21 | 6/21 | 12/21 | 12/21 | 6/21 |

## Leggyakoribb hibák

- **szabi-3b-v7**: nincs tool-hívás ×14, kitalált név: pass ×1, kapott: move,stop ×1, kapott: move ×1
- **szabi-3b-v8**: nincs tool-hívás ×12, kapott: move ×3, tiltott hívás: move ×2, kitalált név: unknown ×1
- **szabi-3b-v9**: nincs tool-hívás ×15, kapott: turn ×2, kapott: move ×1, tiltott hívás: move ×1
- **szabi-3b-v10**: nincs tool-hívás ×15, kapott: turn ×4, kapott: camera ×1, kapott: move ×1
- **szabi-3b-v11e1**: nincs tool-hívás ×13, kapott: turn ×2, kapott: camera ×1, kapott: camera,camera ×1
- **szabi-3b-v11e2**: nincs tool-hívás ×6, kitalált név: speed ×2, kitalált név: wait ×1, kapott: turn ×1
- **szabi-3b-v11e3**: nincs tool-hívás ×5, kapott: turn ×2, kitalált név: wait ×1, kapott: scan_wifi,stop,move ×1
- **llama3.2:3b**: nincs tool-hívás ×24

## Olvasat

- 10 kérdés × 3 ismétlés effektíve **n≈10 tétel**, kisebb tételenkénti zajjal — NEM n=30. Egy 1–2 pontos
  különbség két modell közt nem értelmes; egy 3+ pontos igen.
- A **negatív** kérdéseken a magas pont azt jelenti, hogy a modell NEM tüzelt fölöslegesen. E nélkül a teszt a kapkodást jutalmazná.
- A **memorizált** és az **új** részösszeg különbsége mutatja, mennyi ebből betanult reflex és mennyi általánosítás.
