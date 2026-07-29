"""A role wildcard-ellenorzesenek onallo probaja (ansible nelkul).
Az Ansible `search` testje = re.search. A szurolancot pontosan ugy futtatjuk."""
import re, jinja2

EXPR = ("{{ sockets | select('search', ':11434\\\\s') "
        "| select('search', '(0\\\\.0\\\\.0\\\\.0|\\\\[::\\\\]):11434') "
        "| list | length }}")

env = jinja2.Environment()
env.tests['search'] = lambda s, p: bool(re.search(p, s))

def count(lines):
    return int(env.from_string(EXPR).render(sockets=lines))

# JO: csak a VPN-cimen hallgat (ez volt a mert allapot 2026-07-29-en)
jo = ["LISTEN 0 4096 10.0.0.1:11434 0.0.0.0:*",
      "LISTEN 0 4096 127.0.0.53%lo:53 0.0.0.0:*",
      "LISTEN 0 128 0.0.0.0:22 0.0.0.0:*"]
# ROSSZ: wildcardon hallgat -> a publikus NIC-en is elerheto
rossz_v4 = ["LISTEN 0 4096 0.0.0.0:11434 0.0.0.0:*"]
rossz_v6 = ["LISTEN 0 4096 [::]:11434 [::]:*"]
# Csapda: a 11434 mint FORRAS-port egy mas sorban nem szamit
csapda = ["LISTEN 0 128 0.0.0.0:114340 0.0.0.0:*"]

assert count(jo) == 0, f"a jo allapotot elbukta: {count(jo)}"
assert count(rossz_v4) == 1, "a 0.0.0.0 wildcardot NEM vette eszre"
assert count(rossz_v6) == 1, "a [::] wildcardot NEM vette eszre"
assert count(csapda) == 0, f"tevesen jelzett a 114340 porton: {count(csapda)}"
assert count(jo + rossz_v4) == 1, "kevert bemeneten hibazott"
print("OK - mind az 5 eset helyes (jo=0, v4=1, v6=1, csapda=0, kevert=1)")
