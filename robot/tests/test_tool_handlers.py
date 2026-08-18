"""A `ToolRegistry` és a `scan_wifi` — a nyers modell-szöveg és a hardver közti határ.

Amit itt ellenőrzünk, az a HATÁR viselkedése: a sztringek enumokká oldása (egy rossz
érték hangosan bukjon, ne néma motor-no-op legyen), a hiányzó vezérlő, az `nmcli`
kimenetének feldolgozása. A dispatch SZŰRŐJÉNEK szerződése külön él
(`test_dispatch_contract.py`), mert az biztonsági tétel.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from freedroid.motion.types import Direction, Mode, Speed, TurnDir
from freedroid.tools import handlers
from freedroid.tools.handlers import ToolRegistry, parse_nmcli, scan_wifi
from freedroid.tools.parser import ParsedTool, parse_tools


class FakeMotion:
    """A vezérlő HELYETT — a hívásokat rögzíti, hardvert nem érint."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def move(self, **kw) -> None:
        self.calls.append(("move", kw))

    def turn(self, **kw) -> None:
        self.calls.append(("turn", kw))

    def stop(self) -> None:
        self.calls.append(("stop", {}))

    def set_speed(self, speed) -> None:
        self.calls.append(("set_speed", {"speed": speed}))


class FakeCamera:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def pan(self, direction, degrees) -> None:
        self.calls.append(("pan", direction, degrees))

    def tilt(self, direction, degrees) -> None:
        self.calls.append(("tilt", direction, degrees))

    def action(self, action) -> None:
        self.calls.append(("action", action))


def dispatch_szoveg(reg: ToolRegistry, szoveg: str):
    (tool,) = parse_tools(szoveg)
    return reg.dispatch(tool)


# --- enum-feloldás: a sztring/enum határ ---

def test_move_enumma_oldja_a_sztringeket():
    m = FakeMotion()
    reg = ToolRegistry(motion=m)
    dispatch_szoveg(reg, "<tool>move forward 2 slow</tool>")
    (nev, kw), = m.calls
    assert nev == "move"
    assert kw["direction"] is Direction.FORWARD
    assert kw["speed"] is Speed.SLOW
    assert kw["distance"] == 2.0


def test_turn_fokot_es_iranyt_ad_at():
    m = FakeMotion()
    dispatch_szoveg(ToolRegistry(motion=m), "<tool>turn left 90</tool>")
    (_, kw), = m.calls
    assert kw["direction"] is TurnDir.LEFT and kw["degrees"] == 90


def test_ismeretlen_sebesseg_HANGOSAN_bukik():
    """A lényeg: NEM néma no-op. Egy továbbadott 'turbo' sztringből a vezérlőben
    lenne KeyError vagy — rosszabb — csendben alapértelmezett sebesség."""
    m = FakeMotion()
    reg = ToolRegistry(motion=m)
    with pytest.raises(ValueError):
        reg.dispatch(ParsedTool("set_speed", {"level": "turbo"}))
    assert m.calls == []


def test_hianyzo_vezerlo_hangos_hiba_nem_no_op():
    """A kamera még a szervókra vár — egy `camera` hívás ilyenkor NE tűnjön el csendben."""
    reg = ToolRegistry(motion=FakeMotion())
    with pytest.raises(LookupError):
        dispatch_szoveg(reg, "<tool>camera pan left 45</tool>")


def test_camera_pan_tilt_es_gesztus():
    c = FakeCamera()
    reg = ToolRegistry(camera=c)
    dispatch_szoveg(reg, "<tool>camera pan left 45</tool>")
    dispatch_szoveg(reg, "<tool>camera nod</tool>")
    assert c.calls[0] == ("pan", "left", 45)
    assert c.calls[1][0] == "action"


def test_register_nem_veheti_fel_a_kitalalt_neveket():
    """A `register` nem kerülheti meg a szűrőt: aki a `connect`-et bejegyezné,
    annak a dispatch végre is hajtaná."""
    reg = ToolRegistry()
    with pytest.raises(ValueError):
        reg.register("connect", lambda t: None)


# --- viselkedési kapcsolók ---

def test_set_mode_rogziti_a_modot():
    reg = ToolRegistry()
    assert dispatch_szoveg(reg, "<tool>set_mode standby</tool>") is Mode.STANDBY
    assert reg.mode is Mode.STANDBY


def test_oracle_kikapcsolhato_de_be_nem():
    """SZÁNDÉKOS aszimmetria: a biztonságos irány mindig sikerül, a másik hangosan bukik."""
    reg = ToolRegistry()
    assert dispatch_szoveg(reg, "<tool>set_oracle off</tool>") is False
    with pytest.raises(NotImplementedError):
        dispatch_szoveg(reg, "<tool>set_oracle on</tool>")
    assert reg.oracle_enabled is False


def test_nav_help_visszaadja_a_celt():
    reg = ToolRegistry()
    assert dispatch_szoveg(reg, "<tool>request_navigation_help piros szék</tool>") \
        == "piros szék"


# --- nmcli ---

def test_nmcli_dedup_a_legerosebbet_tartja():
    """Egy konferencia-wifi BSSID-nként ad sort — Szabi ne olvassa fel tucatszor."""
    halok = parse_nmcli("Hacktivity:40:WPA2\nHacktivity:88:WPA2\nHacktivity:12:WPA2\n")
    assert halok == [{"ssid": "Hacktivity", "signal": 88, "security": "WPA2"}]


def test_nmcli_escape_elt_kettospont_a_nevben():
    """`nmcli -t` a mezőn belüli kettőspontot `\\:`-ra escape-eli — sima split szétesne."""
    (halo,) = parse_nmcli("Vendeg\\:Wifi:55:WPA2\n")
    assert halo["ssid"] == "Vendeg:Wifi"


def test_nmcli_ures_biztonsag_NYILT_halozat():
    """A demó üzenete ez a mező: Szabi megmondja, melyik hálózat védtelen."""
    (halo,) = parse_nmcli("SzabadWifi:70:\n")
    assert halo["security"] == "nyílt"


def test_nmcli_rejtett_es_csonka_sorok_kimaradnak():
    assert parse_nmcli(":60:WPA2\ncsonka\nJo:60:WPA2\nRossz:xx:WPA2\n") == [
        {"ssid": "Jo", "signal": 60, "security": "WPA2"}]


def test_scan_wifi_szur_es_rendez(monkeypatch):
    monkeypatch.setattr(handlers.subprocess, "run", lambda *a, **k: SimpleNamespace(
        stdout="Gyenge:20:WPA3\nEros:90:WPA3\nNyilt:80:\n"))
    (tool,) = parse_tools("<tool>scan_wifi filter wpa3 sort signal</tool>")
    assert [h["ssid"] for h in scan_wifi(tool)] == ["Eros", "Gyenge"]


def test_scan_wifi_ismeretlen_rendezes_bukik(monkeypatch):
    monkeypatch.setattr(handlers.subprocess, "run",
                        lambda *a, **k: SimpleNamespace(stdout="A:10:WPA2\n"))
    with pytest.raises(ValueError):
        scan_wifi(ParsedTool("scan_wifi", {"sort": "kozelseg"}))


def test_scan_wifi_a_modell_szovegebol_semmi_nem_kerul_a_parancsba(monkeypatch):
    """A read-only invariáns MÁSIK fele: nincs injekciós felület."""
    latott: list = []
    monkeypatch.setattr(handlers.subprocess, "run", lambda *a, **k: (
        latott.append(a[0]) or SimpleNamespace(stdout="")))
    scan_wifi(ParsedTool("scan_wifi", {"filter": "; rm -rf /", "sort": "ssid"}))
    assert latott == [handlers.NMCLI_SCAN]


def test_scan_wifi_nmcli_hiba_HANGOS(monkeypatch):
    """"Nem találtam hálózatot" és "nem tudtam megnézni" nem ugyanaz."""
    def robban(*a, **k):
        raise OSError("nmcli not found")
    monkeypatch.setattr(handlers.subprocess, "run", robban)
    with pytest.raises(RuntimeError):
        scan_wifi(ParsedTool("scan_wifi", {}))
