"""Openings: a named one is an event, a bare one is routine.

Measured across 35 hand-checked memorias: every one of the 83 entries using
the noun "Apertura", and all 78 using "autorizado", is an entry the author
kept. The routine openings all use the verb and name nobody.
"""

import pytest

from nettune.report.routine_rules import is_noise, is_routine_text, reads_as_event


def hidden(text: str) -> bool:
    return (is_routine_text(text) and not reads_as_event(text)) or is_noise(text)


@pytest.mark.parametrize("entry", [
    "Apertura a técnico de Aguasur cuarto de contadores zona 6 de planta cero.",
    "Apertura de Z-4 P0 para los repartidores de hielo.",
    "Apertura cuadro contadores zona 4 y zona 6 para su lectura (gerencia).",
    "Apertura de puerta principal nº 2 a Tecnobelleza.",
    "Se abre el torreón de zona 6 a los técnicos de Climagran autorizado por gerencia.",
    "Apertura de zona 9 exterior a McFit, autorizado por gerencia.",
    "Se abre el torreón de zona 4 a un técnico de telefonía.",
    "Se abren rampas laterales a los técnicos de AtiSoluciones.",
    "Se abren puertas de emergencia de zona 6 a los repartidores del hielo.",
    "Se abre Z-1 por humo y mal olor.",
    "Se desconecta y se pone un cartel de averiado en un ascensor de zona 6.",
    "Se ponen las pilonas de zona 10 estando la mayoría de los pestillos rotos.",
    "Se conectan rampas mecánicas de subida y bajada por sesión matinal de cine.",
    "Se revisa la zona azul del parking -2 por llamada del compañero.",
    "Se revisan terrazas encontrando abierta una puerta metálica, zona 9.",
    # Found on a real scan: the plural form was hiding the line.
    "Se observan luces encendidas en local 3 de planta 0, se apagan.",
    "Se detectan restos de aceite en la rampa de zona 4.",
])
def test_a_named_opening_reaches_the_document(entry):
    assert not hidden(entry), entry


@pytest.mark.parametrize("entry", [
    "Apertura muelle",
    "Apertura accesos gimnasio",
    "Apertura del acceso nocturno",
    "Inicio del servicio",
    "Finaliza el servicio",
    "Se quitan pilonas Z1, Z2 y Z3",
    "Se retiran pilonas.",
    "Se revisan torreones y se abren (Z9, Z12, Z27)",
    "Se abre Z6-1",
    "Se produce un cierre sin novedad.",
    "Nuevo turno sin incidencias hasta el momento",
])
def test_a_bare_opening_stays_hidden(entry):
    assert hidden(entry), entry


def test_the_noun_still_loses_to_nothing_notable():
    """A seismo is an event whatever else the line says."""
    assert not hidden("Se produce un seísmo sin novedad.")
