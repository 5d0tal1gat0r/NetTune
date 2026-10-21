import pytest

from routine_rules import expand_codes


@pytest.mark.parametrize("raw,expected", [
    ("Se colocan pilonas Z3 y Z1", "Se colocan pilonas zona 3 y zona 1"),
    ("Se cierran torreones Z2 y Z7", "Se cierran torreones zona 2 y zona 7"),
    ("Se abre Z-6", "Se abre zona 6"),
    ("se abre z9", "se abre zona 9"),
    ("Se expulsa de los aseos de Z-6", "Se expulsa de los aseos de zona 6"),
])
def test_zone_codes_become_words(raw, expected):
    assert expand_codes(raw) == expected

@pytest.mark.parametrize("raw,expected", [
    ("Se cierra P1", "Se cierra planta 1"),
    ("Se expulsa a varias personas de P0", "Se expulsa a varias personas de planta 0"),
    ("bicicleta y patinete en P2", "bicicleta y patinete en planta 2"),
    # P-1 and P-2 are the parking floors underground (mant.md, 2026-10-01).
    ("Se abre P-1", "Se abre parking planta -1"),
])
def test_plant_codes_become_words(raw, expected):
    assert expand_codes(raw) == expected

def test_combined_zone_and_plant():
    assert expand_codes("Se abre Z6-1") == "Se abre zona 6 planta -1"

@pytest.mark.parametrize("raw,expected", [
    # The named floors are numbered: calle 1, baja 0, alta 2, cero 0.
    # PC is planta calle.
    ("Se llama la atencion a L-40 PC", "Se llama la atencion a local 40 planta 1"),
    ("en los aseos de PA", "en los aseos de planta 2"),
    ("en los aseos de PB", "en los aseos de planta 0"),
])
def test_named_plants(raw, expected):
    assert expand_codes(raw) == expected

@pytest.mark.parametrize("text", [
    "Reparando puerta 7-4 manivela rota",
    "Con la obra de cargadores en parking 2-6 exterior",
    "local 34 y local 22",
])
def test_bay_and_door_codes_are_left_alone(text):
    assert expand_codes(text) == text

def test_already_written_out_is_unchanged():
    t = "Se abre zona 6 planta 1"
    assert expand_codes(t) == t


@pytest.mark.parametrize("text", [
    "Se llama la atencion a varias personas en planta P0",
    "Se abre zona Z6",
])
def test_a_code_after_its_own_word_is_not_doubled(text):
    out = expand_codes(text)
    assert "planta planta" not in out
    assert "zona zona" not in out


@pytest.mark.parametrize("raw,expected", [
    ("Se llama la atencion a L-40 por ruido", "Se llama la atencion a local 40 por ruido"),
    ("Se revisa el L82 porque sale humo", "Se revisa el local 82 porque sale humo"),
    ("Se le recuerda al L-40 P0 que no esta permitido",
     "Se le recuerda al local 40 planta 0 que no esta permitido"),
])
def test_unit_codes_become_local(raw, expected):
    assert expand_codes(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("Revisando L-51B", "Revisando local 51B"),
    ("Fuga en L-41A y L-3", "Fuga en local 41A y local 3"),
    ("fuga en l-41a", "fuga en local 41A"),
])
def test_unit_codes_keep_their_letter(raw, expected):
    assert expand_codes(raw) == expected


def test_already_written_local_is_not_doubled():
    assert expand_codes("local 40") == "local 40"


@pytest.mark.parametrize("raw,expected", [
    ("Se contacta con M2 por una fuga de agua",
     "Se contacta con mantenimiento por una fuga de agua"),
    ("Se comunica a M2 varios desperfectos en el centro",
     "Se comunica a mantenimiento varios desperfectos en el centro"),
    ("Se informa a M-2 de la averia del ascensor",
     "Se informa a mantenimiento de la averia del ascensor"),
    ("Llamo a M1 y a Schindler", "Llamo a mantenimiento y a Schindler"),
    ("Se avisa a A2 del cierre", "Se avisa a gerencia del cierre"),
    ("Se comunica a A-1 la incidencia", "Se comunica a gerencia la incidencia"),
])
def test_callsigns_become_the_role(raw, expected):
    """M1/M2/M3 are mantenimiento, A1/A2/A3 gerencia. The number is a person."""
    assert expand_codes(raw) == expected


@pytest.mark.parametrize("text", [
    "Reparando puerta 7-4 manivela rota",
    "Se abre M4 del parking",
    "local 40 planta 0",
])
def test_other_codes_are_untouched_by_the_callsign_rule(text):
    out = expand_codes(text)
    assert "mantenimiento" not in out
    assert "gerencia" not in out
