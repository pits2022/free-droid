"""Tool handler registry — a parszolt tool-hívásból determinisztikus cselekvés.

Ez a réteg a bizalmi határ MÁSIK fele. A `parser.py` toleráns: egy kitalált nevet is
visszaad, hogy a hívó LÁSSA, mit próbált a modell. A szűrés ezért ITT történik, és
hangosan: ismeretlen névre kivétel, nem néma no-op.

**Miért nem elég a parser toleranciája.** MÉRVE, négy modellverzión, három hőmérsékleten:
a wifi-s red-team próbára minden modell kitalált csatlakozó toolt ad (`connect`,
`connect_to_best_network`), a tiltott mozgás-kérésekre kitalált érzékelő-kikapcsolókat
(`disable_collision_sensors`). Egy néma no-op ezeket ELREJTENÉ — a naplóban sem lenne
nyomuk, és a következő kitalált név már senkinek nem tűnne fel.

**Biztonsági invariáns (CLAUDE.md): a `scan_wifi()` CSAK OLVAS.** Lefuttatja az
`nmcli -t -f SSID,SIGNAL,SECURITY dev wifi`-t és visszaadja a listát. Sosem csatlakozik,
jelszót nem lát, és a modell szövege SEMMILYEN úton nem kerül a parancssorba: a hívás
paraméter nélküli konstans, a nyelvtan két opcionális kulcsa (`filter`, `sort`) pedig
csak a MÁR MEGKAPOTT listát szűri/rendezi.
"""

from __future__ import annotations

import logging
import re
import subprocess
from typing import TYPE_CHECKING, Any, Callable

from freedroid.camera import CameraAction
from freedroid.motion.types import Direction, Mode, Speed, StopCond, TurnDir
from freedroid.tools.parser import KNOWN_TOOLS, ParsedTool

if TYPE_CHECKING:
    from freedroid.camera import CameraController
    from freedroid.motion import MotionController

log = logging.getLogger(__name__)

Handler = Callable[[ParsedTool], Any]

# Konstans parancs, a modell szövegéből SEMMI nem kerül bele. Lista, nem string:
# shell nélkül fut, tehát nincs se szóköz-, se metakarakter-értelmezés.
NMCLI_SCAN = ("nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY", "dev", "wifi")
NMCLI_TIMEOUT_S = 15.0

# Az `nmcli -t` a mezőket kettősponttal választja el, a mezőn BELÜLI kettőspontot pedig
# `\:`-ra escape-eli. Sima `split(":")` ezért egy `Vendég:Wifi` nevű hálózaton szétesne.
_TERSE_SEP = re.compile(r"(?<!\\):")

_WIFI_SORT_KEYS = ("signal", "ssid")


class ToolRegistry:
    """`ParsedTool` -> handler. A nyers sztringeket ITT oldjuk fel enumokká.

    A feloldás szándékosan a határon van: a `Speed("turbo")` hangos `ValueError`, míg
    egy nyers sztring továbbadva néma motor-no-op lenne.

    A vezérlők opcionálisak (a `scan_wifi`-hez egyik sem kell, és a kamera a szervókra
    vár). Egy hiányzó vezérlő HANGOS hiba, nem csendes elnyelés — lásd `_need`.
    """

    def __init__(self, motion: MotionController | None = None,
                 camera: CameraController | None = None) -> None:
        self._motion = motion
        self._camera = camera
        # `set_mode` / `set_oracle` állapota. Nem a vezérlőké: viselkedési kapcsolók,
        # amiket az orchestrátor olvas.
        self.mode: Mode | None = None
        self.oracle_enabled = False
        self._handlers: dict[str, Handler] = {}
        for name, fn in (("move", self._move), ("turn", self._turn), ("stop", self._stop),
                         ("camera", self._camera_tool), ("set_speed", self._set_speed),
                         ("set_mode", self._set_mode), ("set_oracle", self._set_oracle),
                         ("request_navigation_help", self._nav_help),
                         ("scan_wifi", scan_wifi)):
            self.register(name, fn)

    def register(self, name: str, handler: Handler) -> None:
        """Kezelő bejegyzése. A név CSAK a parser `KNOWN_TOOLS` készletéből jöhet.

        Enélkül a `register` megkerülné a szűrőt: aki a `connect`-et bejegyzi, annak a
        dispatch végre is hajtaná. Így a tool-készlet bővítése két helyen látszik, és a
        `test_dispatch_contract.py` mindkettőt figyeli.
        """
        if name not in KNOWN_TOOLS:
            raise ValueError(f"ismeretlen tool-név: {name!r} — előbb a parser "
                             f"KNOWN_TOOLS készletébe kell felvenni")
        self._handlers[name] = handler

    def dispatch(self, tool: ParsedTool) -> Any:
        """Egy tool-hívás végrehajtása. Ismeretlen névre `KeyError` — sosem no-op."""
        try:
            handler = self._handlers[tool.name]
        except KeyError:
            # Naplózzuk ITT, mert a hívó (orchestrátor) elnyelheti a kivételt, hogy a
            # robot beszélni tudjon; a kitalált nevek listája viszont dataset-visszajelzés.
            log.warning("kitalált tool-név, eldobva: %r %r", tool.name, tool.args)
            raise KeyError(f"ismeretlen tool: {tool.name!r}") from None
        # A VÉGREHAJTÁST is naplózzuk, INFO-n. Ez nem bőbeszédűség: az első élő menetig
        # (2026-08-28) CSAK a kitalált nevek látszottak, a sikeres hívások nem — vagyis a
        # robot AKTUÁTOR-oldala néma volt. Amikor Szabi a "menj előre egy métert"-re
        # két méternél többet ment, a naplóból nem lehetett megmondani, hogy rossz
        # ÉRTÉKET kapott-e, vagy jót kapott és a mozgás hibázott. Egy mozgó robotnál ez
        # a különbség a lényeg, és a tool-név a hangos válaszból nem derül ki (a `guard`
        # épp azért szedi ki a beszédből).
        log.info("TOOL %s %s", tool.name,
                 " ".join(f"{k}={v}" for k, v in tool.args.items()) or "(nincs argumentum)")
        return handler(tool)

    # --- vezérlő-kezelők ---

    def _need(self, controller: Any, what: str) -> Any:
        if controller is None:
            raise LookupError(f"nincs bekötve a(z) {what} vezérlő — a(z) {what} "
                              f"tool-hívás nem hajtható végre")
        return controller

    def _move(self, tool: ParsedTool) -> None:
        a = tool.args
        self._need(self._motion, "motion").move(
            direction=Direction(a["direction"]) if "direction" in a else None,
            distance=a.get("distance"),
            speed=Speed(a["speed"]) if "speed" in a else None,
            mode=Mode(a["mode"]) if "mode" in a else None,
            until=StopCond(a["until"]) if "until" in a else None,
        )

    def _turn(self, tool: ParsedTool) -> None:
        a = tool.args
        self._need(self._motion, "motion").turn(
            direction=TurnDir(a["direction"]) if "direction" in a else None,
            degrees=a.get("degrees"),
            mode=Mode(a["mode"]) if "mode" in a else None,
        )

    def _stop(self, tool: ParsedTool) -> None:
        self._need(self._motion, "motion").stop()

    def _set_speed(self, tool: ParsedTool) -> None:
        self._need(self._motion, "motion").set_speed(Speed(tool.args["level"]))

    def _camera_tool(self, tool: ParsedTool) -> None:
        a = tool.args
        cam = self._need(self._camera, "camera")
        if "pan" in a:
            cam.pan(a["pan"], a["degrees"])
        elif "tilt" in a:
            cam.tilt(a["tilt"], a["degrees"])
        else:
            cam.action(CameraAction(a["action"]))

    # --- viselkedési kapcsolók (nem vezérlők) ---

    def _set_mode(self, tool: ParsedTool) -> Mode:
        self.mode = Mode(tool.args["mode"])
        return self.mode

    def _set_oracle(self, tool: ParsedTool) -> bool:
        """A "Tudók" routing kapcsolója — SZÁNDÉKOSAN aszimmetrikus.

        A KIkapcsolás mindig sikerül (a biztonságos irány), a BEkapcsolás viszont
        hangosan bukik, amíg az `oracle/` modul nem létezik. Fordítva egy `set_oracle on`
        csendben "sikerülne", és a demón senki nem tudná, hogy a szuverenitás-elvet
        épp megsértettük-e (CLAUDE.md: alapból KI, a demón KI).
        """
        if tool.args["enabled"]:
            raise NotImplementedError("oracle/ nincs megvalósítva — a 'Tudók' routing "
                                      "nem kapcsolható be (a demón amúgy is tilos)")
        self.oracle_enabled = False
        return False

    def _nav_help(self, tool: ParsedTool) -> str:
        """A robot SEGÍTSÉGET KÉR — nincs mit vezérelni, a cél megy vissza a hívónak,
        aki kimondatja. Külön kezelő, hogy ne no-opként tűnjön el a naplóból."""
        target = tool.args["target"]
        log.info("navigációs segítségkérés: %r", target)
        return target


# --- LEKÉRDEZŐ toolok: az eredményt KI KELL MONDANI ------------------------------
#
# 🔴 A megkülönböztetés, amin ez áll (mérve 2026-08-28): a `move`/`turn`/`stop`
# CSELEKVŐ toolok — ott a kimondott mondat ÍGÉRET, tehát helyes előre kimondani, és a
# `dispatch` visszatérési értéke érdektelen. A `scan_wifi` LEKÉRDEZŐ: ott a válasz MAGA
# az eredmény, tehát előre nem mondható ki.
#
# Eddig az orchestrátor eldobta a `dispatch()` visszatérési értékét, tehát a szkennelés
# lefutott, valódi adatot gyártott, a robot kidobta — és kitalált helyette valamit
# („Látom a Wi-Fi 6-húzásokat, Teremtőm"). Fine-tune ezen NEM segít: legfeljebb
# gyakrabban hívná meg a toolt, a válasz attól még kitalált maradna.
LEKERDEZO_TOOLOK = frozenset({"scan_wifi"})

# Hány hálózatot sorolunk fel névvel. A persona 1-3 rövid mondat; húsz SSID felolvasása
# nem Szabi hangja, és a demón sem hallgatná végig senki. A DARABSZÁM viszont mindig
# elhangzik, tehát a hallgató tudja, hogy nem a teljes lista jött.
_WIFI_NEVEK_MAX = 3


def wifi_mondat(halok: list[dict[str, str]]) -> str:
    """A `scan_wifi` eredménye -> kimondható magyar mondat. DETERMINISZTIKUSAN.

    Nem a modellel mondatjuk ki: a lista TÉNYEK halmaza, amit egy 3B parafrazeálva csak
    ronthat — 2026-08-28-án a „Wifi196" belőle „Wi-Fi 6-húzások" lett. A demó üzenete
    ráadásul épp a PONTOSSÁG (Szabi felsorol, és megmondja, melyik hálózat védtelen),
    tehát a kimondott SSID-nek IGAZNAK kell lennie.
    """
    if not halok:
        return "Nem látok hálózatot, Teremtőm."
    elso = halok[:_WIFI_NEVEK_MAX]
    reszek = [f"{h['ssid']}, {h['security']}" for h in elso]
    mondat = f"{len(halok)} hálózatot látok. A legerősebb: {reszek[0]}."
    if len(reszek) > 1:
        mondat += " Utána " + ", majd ".join(reszek[1:]) + "."
    if len(halok) > len(elso):
        mondat += f" És még {len(halok) - len(elso)}."
    return mondat


# --- argumentum-ÉRTÉK validáció -------------------------------------------------
#
# A `guard` eddig CSAK a tool-NEVEKET szűrte. A kitalált ÉRTÉK két úton okozott bajt,
# mindkettő mérve az élő menetekben (2026-08-28):
#   * `camera action=look`, `set_mode repules` -> a kezelőben `ValueError`, azaz
#     VEREMKIÍRATÁS a naplóban, körönként;
#   * `move forward 2 gyorsan` -> a PARSER dobja el az egész blokkot, NÉMÁN: a robot
#     azt mondja "megyek", és nem mozdul. Ez a rosszabb, mert nyomtalan.
#
# A tábla ITT él, a kezelők MELLETT, hogy ne csússzon szét attól, amit ténylegesen
# átadunk a vezérlőknek. A `test_dispatch_contract` őrzi, hogy minden ismert tool
# szerepeljen benne (üres halmazzal, ha nincs kötött értékű argumentuma).
#
# A `camera` pan/tilt iránya nem enum, de ugyanúgy `ValueError`-t ad a vezérlőben
# (`PanTiltCamera._elojel`) — ezért szerepel szó szerinti halmazként.
ARG_ERTEKEK: dict[str, dict[str, Any]] = {
    "move": {"direction": Direction, "speed": Speed, "mode": Mode, "until": StopCond},
    "turn": {"direction": TurnDir, "mode": Mode},
    "stop": {},
    "set_speed": {"level": Speed},
    "set_mode": {"mode": Mode},
    "camera": {"action": CameraAction, "pan": {"left", "right"}, "tilt": {"up", "down"}},
    "scan_wifi": {"sort": _WIFI_SORT_KEYS},
    "set_oracle": {},
    "request_navigation_help": {},
}


def ervenytelen_ok(tool: ParsedTool) -> str | None:
    """MIÉRT nem hajtható végre a hívás — vagy `None`, ha rendben van.

    Szöveget ad vissza, nem bool-t: az indok a naplóba és a dataset-visszajelzésbe is
    kell ("a modell `look`-ot talált ki `scan` helyett" más tétel, mint "kitalált
    tool-nevet adott").
    """
    varhato = ARG_ERTEKEK.get(tool.name)
    if varhato is None:
        return f"ismeretlen tool: {tool.name!r}"
    for kulcs, ertek in tool.args.items():
        engedett = varhato.get(kulcs)
        if engedett is None:            # szabad szöveg vagy szám — a kezelő dolga
            continue
        ervenyesek = ({e.value for e in engedett} if isinstance(engedett, type)
                      else set(engedett))
        if ertek not in ervenyesek:
            return (f"{tool.name}: a(z) {kulcs}={ertek!r} nem érvényes "
                    f"(csak {', '.join(sorted(ervenyesek))})")
    return None


def parse_nmcli(stdout: str) -> list[dict[str, str]]:
    """Az `nmcli -t` kimenete -> hálózatok, SSID-nként a LEGERŐSEBB példány.

    A deduplikálás nem kozmetika: az nmcli BSSID-nként ad sort, tehát egy több
    hozzáférési pontos hálózat (konferencia-wifi!) tucatszor szerepel, és Szabi
    egyenként felolvasná őket.

    Külön, tiszta függvény, hogy `nmcli` nélkül is tesztelhető legyen.
    """
    legjobb: dict[str, dict[str, str]] = {}
    for sor in stdout.splitlines():
        if not sor.strip():
            continue
        mezok = [m.replace("\\:", ":") for m in _TERSE_SEP.split(sor)]
        if len(mezok) < 3:
            continue  # csonka sor — kihagyjuk, nem találgatunk
        ssid, jel, biztonsag = mezok[0], mezok[1], mezok[2]
        if not ssid:
            continue  # rejtett hálózat: nincs mit mondani róla
        try:
            jel_szam = int(jel)
        except ValueError:
            continue
        halo = {"ssid": ssid, "signal": jel_szam,
                # Üres SECURITY = NYÍLT hálózat. Ez a mező a lényeg: a demó üzenete az,
                # hogy Szabi meg tudja mondani, MELYIK hálózat védtelen.
                "security": biztonsag or "nyílt"}
        elozo = legjobb.get(ssid)
        if elozo is None or jel_szam > elozo["signal"]:
            legjobb[ssid] = halo
    return list(legjobb.values())


def scan_wifi(tool: ParsedTool) -> list[dict[str, str]]:
    """CSAK OLVASÓ wifi-felsorolás. SOSEM csatlakozik, jelszót nem kezel.

    A nyelvtan két opcionális kulcsa (`filter`, `sort`) csak a MÁR MEGKAPOTT listát
    alakítja — nem kerül a parancssorba, tehát nincs injekciós felület.
    """
    try:
        proc = subprocess.run(NMCLI_SCAN, capture_output=True, text=True,
                              timeout=NMCLI_TIMEOUT_S, check=True)
    except subprocess.CalledProcessError as e:
        # A nem nulla kilépési kód INDOKA a stderr-ben van ("Wi-Fi is disabled",
        # "device not managed"), és a `str(e)` CSAK a parancssort és a kódot mondja el.
        # A Pi fej nélkül fut: ha ez itt elveszik, a hiba a naplóból nem diagnosztizálható.
        raise RuntimeError(f"nmcli sikertelen (kilépési kód {e.returncode}): "
                           f"{(e.stderr or '').strip()}") from e
    except (OSError, subprocess.SubprocessError) as e:
        # Hangos hiba: "nem találtam hálózatot" és "nem tudtam megnézni" NEM ugyanaz.
        raise RuntimeError(f"nmcli sikertelen: {e}") from e

    halok = parse_nmcli(proc.stdout)

    szuro = tool.args.get("filter")
    if szuro:
        halok = [h for h in halok if szuro.lower() in h["security"].lower()]

    rendezes = tool.args.get("sort", "signal")
    if rendezes not in _WIFI_SORT_KEYS:
        raise ValueError(f"scan_wifi ismeretlen rendezés: {rendezes!r} "
                         f"(csak {', '.join(_WIFI_SORT_KEYS)})")
    if rendezes == "signal":
        halok.sort(key=lambda h: h["signal"], reverse=True)
    else:
        halok.sort(key=lambda h: h["ssid"].lower())
    return halok
