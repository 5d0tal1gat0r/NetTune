import pytest

from memoria_blocks import (
    ASCENSORES,
    BLOCKS,
    ELECTRICIDAD,
    OTROS,
    PARKING,
    SHORT_NAMES,
    SLUGS,
    block_from_slug,
    classify,
    decide,
    normalise,
    slug_of,
)


def test_four_blocks_match_the_document():
    assert BLOCKS == (ELECTRICIDAD, ASCENSORES, PARKING, OTROS)


@pytest.mark.parametrize("raw,expected", [
    ("Electricidad y Alumbrado", ELECTRICIDAD),
    ("electricidad", ELECTRICIDAD),
    ("Ascensores, rampas, escaleras y puertas", ASCENSORES),
    ("Parking", PARKING),
    ("Otros", OTROS),
])
def test_normalises_model_answers(raw, expected):
    assert normalise(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "algo raro", 7])
def test_unknown_model_answer_is_empty(raw):
    assert normalise(raw) == ""


# Real entries from the hand-written JUNIO memoria, under their real headings.
@pytest.mark.parametrize("text,expected", [
    ("Revisando cuadros electricos.", ELECTRICIDAD),
    ("Reponiendo luz en aseo zona 6 planta 1 (plc 26w).", ELECTRICIDAD),
    ("Desmontando focos en columna planta 0.", ELECTRICIDAD),
    ("Con Schindler para ascensor zona 6.", ASCENSORES),
    ("Reparando puerta emergencia zona 4 planta 1 manivela rota.", ASCENSORES),
    ("Con la obra de cargadores del parking por Endesa (1H).", PARKING),
    ("Sumidero en parking planta -1 zona 1 esta muy hundido.", PARKING),
    ("Con averia de aire local 1 planta 1.", OTROS),
    ("Compra en Comasar correa para equipos sedical.", OTROS),
    ("Limpieza fosa septica con agua.", OTROS),
])
def test_classifies_real_entries(text, expected):
    assert classify(text) == expected


# The author files a meter visit and the public-address system under Otros:
# the meter belongs to the utility, and megafonía is not the lighting crew's
# work. From the hand-labelled September 2026 lines.
@pytest.mark.parametrize("text", [
    "Con Endesa para revisar contador del local 46 planta 0. (por estar desprogramado).",
    "Con Aguasur para desmontaje de contador de agua L-49B",
    "Aviso de agua en C-7 planta 2, llave de contador rota.",
    "Avería de megafonía por micro corte de red eléctrica.",
])
def test_meters_and_megafonia_are_otros(text):
    assert classify(text) == OTROS


def test_a_meter_in_the_parking_is_still_parking():
    assert classify("Con ATIS para la reforma de contador en parking (3 horas)") == PARKING


def test_parking_wins_when_both_apply():
    """A door in the parking is filed under Parking in the author's document."""
    assert classify("Reponiendo puertas en parking planta -1 manivelas rotas") == PARKING


def test_anything_unclassifiable_lands_in_otros():
    assert classify("Algo completamente distinto") == OTROS


def test_model_answer_is_used_when_valid():
    assert decide("Parking", "Revisando cuadros electricos") == PARKING


def test_falls_back_to_the_text_when_model_answer_is_junk():
    assert decide("banana", "Revisando cuadros electricos") == ELECTRICIDAD


def test_falls_back_when_model_says_nothing():
    assert decide(None, "Con Schindler para ascensor zona 6") == ASCENSORES


class TestSlugs:
    def test_every_block_has_a_slug_and_a_short_name(self):
        assert list(SLUGS.values()) == list(BLOCKS)
        assert set(SHORT_NAMES) == set(BLOCKS)

    def test_the_names_are_the_ones_the_page_shows(self):
        assert SLUGS == {"electricidad": ELECTRICIDAD, "ascensores": ASCENSORES,
                         "parking": PARKING, "otros": OTROS}
        assert SHORT_NAMES[ASCENSORES] == "Ascensores"
        assert SHORT_NAMES[ELECTRICIDAD] == "Electricidad"

    def test_round_trip(self):
        for slug, block in SLUGS.items():
            assert slug_of(block) == slug
            assert block_from_slug(slug) == block

    def test_unknown_values_give_nothing(self):
        assert slug_of("Intervenciones Seguridad:") == ""
        assert block_from_slug("") == ""
        assert block_from_slug(None) == ""
        assert block_from_slug("<script>") == ""
        assert block_from_slug("Parking") == "Parking", "case does not matter"
