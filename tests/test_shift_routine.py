"""Lighting, closing-round and bollard routine: omitted, unless it is a fault."""

import importlib.util
import os

import pytest

from nettune.report.entry_store import EntryStore
from nettune.report.memoria import SEGURIDAD_BLOCK
from nettune.report.routine_rules import is_routine_text, is_shift_routine


@pytest.mark.parametrize("text", [
    # September's own, as the model read them.
    "Conector [?] alumbrado tarde.", "Conector del alumbrado noche.",
    "Comienzo el cierre.", "Finalizo cierre.", "Se colocan pelonas.",
    # And the ordinary forms.
    "Se conecta alumbrado de tarde", "Se desconecta el alumbrado nocturno",
    "Alumbrado exterior encendido", "Se apaga el alumbrado de noche",
    "Inicio del cierre", "Finaliza el cierre del centro",
    "Se retiran pilonas Z3 y Z1", "Retirada de pilonas", "Se ponen pilonas zona 1",
])
def test_routine_is_omitted(text):
    assert is_shift_routine(text)
    assert is_routine_text(text)


@pytest.mark.parametrize("text", [
    "El alumbrado de tarde no funciona",
    "Falla el alumbrado de noche en zona 4",
    "Alumbrado exterior fundido",
    "Se ven las cámaras por micro cortes de luz.",
    "Se observan luces y puerta abierta en local 39",
    "Se conectan luces para la feria.",
    "Se colocan pilonas en zona 10, Markdene nos pide otra vez dejar el vehículo sin autorización.",
    "Se le comunica al kebab que cierre su puerta interior",
    # Approved in the hand-revised memorias: each says something more.
    "Se quitan las pilonas para la carga del catering de Mae Vest.",
    "Se colocan pilonas en la zona de carga y descarga quedando dentro un Citroën Berlingo.",
    "Se conecta el alumbrado de tarde de manera parcial debido a la poca claridad del día.",
    "Se activa el alumbrado de tarde parcialmente por lluvia.",
    "Conectando alumbrado de navidad.",
    "Colocando pegatinas refractarias en pilonas parking.",
])
def test_a_fault_or_an_incident_stays(text):
    assert not is_shift_routine(text)


def test_the_tool_removes_only_those_and_never_a_hand_edited_line(tmp_path):
    spec = importlib.util.spec_from_file_location(
        "omit_shift_routine", os.path.join(os.path.dirname(__file__), "..",
                                           "tools", "omit_shift_routine.py"))
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    with EntryStore(str(tmp_path / "r.sqlite3")) as store:
        store.add("2026", "SEPTIEMBRE", SEGURIDAD_BLOCK, [
            {"text": "Comienzo el cierre.", "confident": False},
            {"text": "Se colocan pelonas.", "confident": False},
            {"text": "Falla el alumbrado de noche.", "confident": True},
            {"text": "Se llama la atención a un cliente.", "confident": True},
        ], "s.pdf", "01-09-2026 p1")
        kept = next(e for e in store.month_entries("2026", "SEPTIEMBRE")
                    if e["text"] == "Se colocan pelonas.")
        store.edit_entry(kept["id"], "Se colocan pilonas.")
        assert [e["text"] for e in tool.plan(store, "2026", "SEPTIEMBRE")] == [
            "Comienzo el cierre."]


def test_a_maintenance_line_is_never_removed_by_the_tool(tmp_path):
    spec = importlib.util.spec_from_file_location(
        "omit_shift_routine", os.path.join(os.path.dirname(__file__), "..",
                                           "tools", "omit_shift_routine.py"))
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    with EntryStore(str(tmp_path / "m.sqlite3")) as store:
        store.add("2026", "SEPTIEMBRE", "Electricidad y Alumbrado:",
                  [{"text": "Se conecta alumbrado de tarde.", "confident": True}],
                  "m.pdf", "01-09-2026 p1")
        assert tool.plan(store, "2026", "SEPTIEMBRE") == []


@pytest.mark.parametrize("text", [
    "se revisan torreones y se abren.",   # September's: noun before verb
    "Se abren torreones", "Se cierran torreones Z2 y Z3", "Cierre de torreones",
    "Se abren torretas",
])
def test_opening_or_closing_the_torreones_is_routine(text):
    assert is_routine_text(text)


@pytest.mark.parametrize("text", [
    'Apertura de torreón zona 4, a "Mae Vest", (gerencia).',
    "Se abre el torreon de zona 4 a un tecnico de telefonia",
    "Se van los trabajadores de Yoigo, y cierro torreón de zona 4.",
    "Torreón de zona 6 abierto, se cierra y se avisa a mantenimiento",
])
def test_a_torreon_opened_for_someone_stays(text):
    assert not is_routine_text(text)


@pytest.mark.parametrize("text", [
    "Salida clientes Poker", "Salida empleada Poker.", "Salida de clientes del Posier",
    "Salen los clientes del Poker", "Salida encargada Poker",
    "Se incorpora V.S", "Se incorpora VS.", "Incorporación del VS noche.",
    "Se incorpora el vigilante de noche", "Vigilante de noche",
    "Se incorpora el vigilante de modo nocturno.",
])
def test_the_poker_emptying_and_the_guard_coming_on_are_routine(text):
    assert is_shift_routine(text)


@pytest.mark.parametrize("text", [
    "Avisan del Poker para expulsar a un cliente",
    "Al salir la empleada del Poker me comenta que se le han olvidado las llaves del local.",
    "Salida clientes Poker, se llama la atención a uno por gritar.",
    "Encuentro patinete con cadena. Se lo comunico a V.S. Me dice que le ponga una cadena.",
    "Se llama la atención a unos clientes del Poker por estar andando por el centro.",
])
def test_what_happens_around_the_poker_or_the_guard_stays(text):
    assert not is_shift_routine(text)
    assert not is_routine_text(text)


@pytest.mark.parametrize("text", [
    # The daily signs on the stairs and the 3-6 corridor, as the model read them.
    "Se colocan carteles en escaleras y pasillo B-6.",
    "Se colocan carteles de escalera y pasillo 3-6.",
    "Se colocan carteles en escalera y parda [?] 3-6.",
    "Se colocan carteles en escaleras y pasarela 3-6.",
    "Coloco carteles en escaleras y pasillo 3-6.",
    "Se colocan carteles en escaleras y pasillo 36.",
    "Se coloca cartel en pasillo 3-6.",
])
def test_the_daily_signs_on_the_stairs_and_corridor_are_routine(text):
    assert is_shift_routine(text)


@pytest.mark.parametrize("text", [
    "Se colocan carteles de prohibido el paso en la escalera de subida, para evitar "
    "críticas posibles, a la espera de que se persone Schindler.",
    "Se colocan carteles en los ascensores de zona 4.",
    "Se coloca cartel de averiado a máquina de aire de zona 6.",
    "Se entregan carteles en Academia Corazón, planta g.",
    "Se llama la atención a varias clientas de Carrefour por subir las escaleras "
    "estando paradas y quitar cartel...",
])
def test_other_signs_stay(text):
    assert not is_shift_routine(text)


@pytest.mark.parametrize("text", [
    # The exit sign put out at zona 4 every day. "7-4" is how the model reads
    # "Z-4", and "[?]" a zona it could not read.
    "Se coloca cartel de salida en zona 4 planta 1.",
    "Se coloca cartel de salida en zona 4, planta 1.",
    "Coloco cartel de salida en zona 4 planta 1.",
    "Se coloca cartel de salida de zona 4.",
    "Se coloca cartel de salida de zona [?].",
    "Se coloca cartel de salida en 7-4, planta 1.",
    "Se coloca el cartel zona 4.",
    "Se coloca cartel en zona 4.",
])
def test_the_daily_exit_sign_at_zona_4_is_routine(text):
    assert is_shift_routine(text)


@pytest.mark.parametrize("text", [
    "Se colocan carteles en los ascensores de zona 4.",
    "Se coloca cartel grande en zona 3.",
    "Se coloca cartel en zona 4 por avería de la escalera mecánica.",
    "Se colocan carteles para cerrar baños en pasillos 1-4 y en escalera mecánica.",
])
def test_other_signs_in_zona_4_stay(text):
    assert not is_shift_routine(text)
