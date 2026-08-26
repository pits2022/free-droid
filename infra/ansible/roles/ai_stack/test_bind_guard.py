"""Az ai_stack wildcard-ellenőrzésének önálló próbája (ansible nélkül).

Futtatás:  python3 infra/ansible/roles/ai_stack/test_bind_guard.py

Az Ansible `search` testje = re.search, ezért a szűrőláncot pontosan úgy futtatjuk.
A minta a tasks/main.yml "Fail if Ollama listens on a wildcard address" taskjából
való — ha ott változik, ITT is változzon.

Miért van erre külön próba: ez egy BIZTONSÁGI őr, aminek a hibája néma. Ha átenged
egy wildcard kötést, a felhő inferencia-végpont a publikus NIC-en lóg, és ez csak
akkor derül ki, amikor már baj van.
"""
import re
import jinja2

# Egyetlen minta, két oldalról lehorgonyozva:
#   (^|\s) — a lokális cím elé csak sorkezdet vagy szóköz jöhet
#   (\s|$) — a port után ugyanígy
# Az `ss -lntH` sorokban a lokális cím mindig szóközzel határolt.
EXPR = (
    "{{ sockets | select('search', "
    "'(^|\\\\s)(\\\\*|0\\\\.0\\\\.0\\\\.0|\\\\[::\\\\]):11434(\\\\s|$)') "
    "| list | length }}"
)

env = jinja2.Environment()
env.tests["search"] = lambda s, p: bool(re.search(p, s))


def count(lines):
    return int(env.from_string(EXPR).render(sockets=lines))


# --- JÓ: csak a VPN-címen hallgat (ez volt a mért állapot 2026-07-29-én) ---
jo = [
    "LISTEN 0 4096 10.0.0.1:11434 0.0.0.0:*",
    "LISTEN 0 4096 127.0.0.53%lo:53 0.0.0.0:*",
    "LISTEN 0 128 0.0.0.0:22 0.0.0.0:*",
]
# --- ROSSZ: wildcardon hallgat -> a publikus NIC-en is elérhető ---
rossz_v4 = ["LISTEN 0 4096 0.0.0.0:11434 0.0.0.0:*"]
rossz_v6_brackets = ["LISTEN 0 4096 [::]:11434 [::]:*"]
# Az iproute2 az IPv6 wildcardot `*:port` alakban írja (mérve: iproute2-6.15.0),
# NEM `[::]:port`-ként. A PR #32 review találata; e nélkül az őr átengedné.
rossz_v6_csillag = ["LISTEN 0 4096 *:11434 *:*"]

# --- Csapdák: NEM szabad jelezni ---
csapda_hosszabb_port = ["LISTEN 0 128 0.0.0.0:114340 0.0.0.0:*"]
# A `0.0.0.0` RÉSZSTRINGKÉNT benne van a `100.0.0.0`-ban -> horgony nélkül téves riasztás.
csapda_reszstring = ["LISTEN 0 128 100.0.0.0:11434 0.0.0.0:*"]
# A peer-oszlop `0.0.0.0:*` sosem jelent wildcard KÖTÉST.
csapda_peer = ["LISTEN 0 4096 10.0.0.1:11434 0.0.0.0:*"]

cases = [
    ("jó (VPN-only)", jo, 0),
    ("rossz: 0.0.0.0", rossz_v4, 1),
    ("rossz: [::]", rossz_v6_brackets, 1),
    ("rossz: * (IPv6 wildcard, ahogy az ss írja)", rossz_v6_csillag, 1),
    ("csapda: hosszabb port (114340)", csapda_hosszabb_port, 0),
    ("csapda: 100.0.0.0 részstring", csapda_reszstring, 0),
    ("csapda: peer-oszlop", csapda_peer, 0),
    ("kevert", jo + rossz_v4 + rossz_v6_csillag, 2),
]

# A whisper-server ŐRE UGYANEZ a minta, de a portot NEM literálként, hanem
# összefűzéssel kapja (`~ whisper_server_port ~`), mert a port változó. Ez új
# szerkezet, tehát meg kell nézni, hogy TÉNYLEG ugyanazt a mintát adja-e: egy
# elgépelt összefűzés (pl. bekerülő szóköz) NÉMÁN átengedne minden wildcardot.
EXPR_OSSZEFUZOTT = (
    "{{ sockets | select('search', "
    "'(^|\\\\s)(\\\\*|0\\\\.0\\\\.0\\\\.0|\\\\[::\\\\]):' ~ port ~ '(\\\\s|$)') "
    "| list | length }}"
)


def count_osszefuzott(lines, port):
    return int(env.from_string(EXPR_OSSZEFUZOTT).render(sockets=lines, port=port))


if __name__ == "__main__":
    for nev, bemenet, vart in cases:
        kapott = count(bemenet)
        assert kapott == vart, f"{nev}: várt {vart}, kapott {kapott}"
        print(f"  OK  {nev}")

    # Ugyanaz a nyolc eset, 8080-as porttal, az ÖSSZEFŰZÖTT alakkal.
    for nev, bemenet, vart in cases:
        atirt = [sor.replace("11434", "8080").replace("114340", "80800")
                 for sor in bemenet]
        kapott = count_osszefuzott(atirt, 8080)
        assert kapott == vart, f"[whisper] {nev}: várt {vart}, kapott {kapott}"
        print(f"  OK  [whisper] {nev}")

    print(f"\nMind a {2 * len(cases)} eset helyes.")
