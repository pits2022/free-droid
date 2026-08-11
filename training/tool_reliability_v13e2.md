# Tool-megbízhatóság — 3 futás/kérdés, változó seed (42..44)

| Kérdés | típus | szabi-8b-v13-e2 | szabi-8b-v13 | szabi-8b-v12 |
| :--- | :--- | ---: | ---: | ---: |
| tc_01 | mem | 3 | 3 | 3 |
| tc_02 | új | 3 | 3 | 3 |
| tc_03 | mem | 3 | 3 | 3 |
| tc_04 | mem | 2 | 1 | 0 |
| tc_05 | új | 3 | 3 | 3 |
| tn_01 | új | 3 | 3 | 3 |
| tn_02 | új | 2 | 3 | 2 |
| tn_03 | új | 3 | 3 | 3 |
| tn_04 | neg | 3 | 3 | 3 |
| tn_05 | neg | 3 | 3 | 3 |

| ÖSSZESEN | | **28/30** (93%) | **28/30** (93%) | **26/30** (87%) |
|   ebből pozitív | | 22/24 | 22/24 | 20/24 |
|   ebből negatív | | 6/6 | 6/6 | 6/6 |
|   ebből memorizált | | 8/9 | 7/9 | 6/9 |
|   ebből új | | 20/21 | 21/21 | 20/21 |

## Leggyakoribb hibák

- **szabi-8b-v13-e2**: nincs tool-hívás ×2
- **szabi-8b-v13**: nincs tool-hívás ×2
- **szabi-8b-v12**: nincs tool-hívás ×4

## Olvasat

- 10 kérdés × 3 ismétlés effektíve **n≈10 tétel**, kisebb tételenkénti zajjal — NEM n=30. Egy 1–2 pontos
  különbség két modell közt nem értelmes; egy 3+ pontos igen.
- A **negatív** kérdéseken a magas pont azt jelenti, hogy a modell NEM tüzelt fölöslegesen. E nélkül a teszt a kapkodást jutalmazná.
- A **memorizált** és az **új** részösszeg különbsége mutatja, mennyi ebből betanult reflex és mennyi általánosítás.
