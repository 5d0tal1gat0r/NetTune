"""Two kinds of sheet arrive: mantenimiento and seguridad.

They need different vocabulary when read and different treatment when filed,
so the type has to be identified reliably. The model is asked for it, but a
deterministic classifier backs that up -- a missing or invented type must never
silently route a sheet to the wrong filter.
"""

import pytest

from nettune.pages.document_type import MANTENIMIENTO, SEGURIDAD, UNKNOWN, classify, normalise

# --- normalising whatever the model returned ------------------------------


@pytest.mark.parametrize("raw", ["mantenimiento", "MANTENIMIENTO", " Mantenimiento ",
                                 "ficha de mantenimiento", "manteniminto"])
def test_normalises_maintenance_spellings(raw):
    assert normalise(raw) == MANTENIMIENTO


@pytest.mark.parametrize("raw", ["seguridad", "SEGURIDAD", "ficha de seguridad",
                                 "vigilancia", "segurida"])
def test_normalises_security_spellings(raw):
    assert normalise(raw) == SEGURIDAD


@pytest.mark.parametrize("raw", [None, "", "otra cosa", "hoja rara", 42])
def test_unrecognised_values_become_unknown(raw):
    assert normalise(raw) == UNKNOWN


# --- classifying from the page content ------------------------------------


def test_maintenance_title_wins():
    assert classify("FICHA DIARIA DE TRABAJO DE MANTENIMIENTO", []) == MANTENIMIENTO


def test_security_title_wins():
    assert classify("PARTE DIARIO DE SERVICIO DE SEGURIDAD", []) == SEGURIDAD


def test_maintenance_recognised_from_its_vocabulary():
    entries = ["Revisando cuadros eléctricos",
               "Conectando mg de aire",
               "Con la obra de cargadores en parking 2-6 exterior"]
    assert classify("", entries) == MANTENIMIENTO


def test_security_recognised_from_its_vocabulary():
    entries = ["Inicio del servicio",
               "Se quitan pilonas Z1, Z2 y Z3",
               "Se revisan torreones y se abren (Z9, Z12)",
               "Finaliza el servicio"]
    assert classify("", entries) == SEGURIDAD


def test_the_service_bookend_is_a_strong_security_signal():
    assert classify("", ["Inicio del servicio", "Finaliza el servicio"]) == SEGURIDAD


def test_zone_codes_are_a_security_signal():
    assert classify("", ["Se colocan pilonas Z10 y se cierra portón Z4"]) == SEGURIDAD


def test_parking_bay_codes_are_a_maintenance_signal():
    assert classify("", ["Reparando puerta 7-4 P-1 manivela rota",
                         "Revisando cuadros eléctricos"]) == MANTENIMIENTO


def test_an_empty_page_is_unknown():
    assert classify("", []) == UNKNOWN


def test_ambiguous_content_is_unknown_rather_than_guessed():
    """Both vocabularies mention the muelle and the alumbrado."""
    assert classify("", ["Apertura del muelle", "Conexión del alumbrado"]) == UNKNOWN


def test_a_trusted_model_answer_is_used_when_content_is_ambiguous():
    from nettune.pages.document_type import decide

    assert decide("seguridad", "", ["Apertura del muelle"]) == SEGURIDAD


def test_content_overrides_a_model_answer_that_contradicts_it():
    """A confident vocabulary match beats the model's label."""
    from nettune.pages.document_type import decide

    entries = ["Revisando cuadros eléctricos", "Conectando mg de aire",
               "Con la obra de cargadores en parking 2-6"]
    assert decide("seguridad", "", entries) == MANTENIMIENTO


def test_unknown_model_answer_falls_back_to_content():
    from nettune.pages.document_type import decide

    assert decide(None, "FICHA DIARIA DE TRABAJO DE MANTENIMIENTO", []) == MANTENIMIENTO
