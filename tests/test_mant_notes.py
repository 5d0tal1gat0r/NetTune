"""The maintenance notes (mant.md): floor codes, máquinas, company names,
routine, and the two signs that a line is Parking."""

import pytest

from consensus import consolidate
from filtering_agents import apply_filter
from memoria_blocks import ELECTRICIDAD, OTROS, PARKING, decide
from routine_rules import expand_codes, expand_maintenance_terms, is_routine_text, name_companies


@pytest.mark.parametrize("raw, expected", [
    ("Revisando luces P/C", "Revisando luces planta 1"),
    ("Puerta de emergencia P/A", "Puerta de emergencia planta 2"),
    ("Fuga en P/0", "Fuga en planta 0"),
    ("Fuga en P/Ø", "Fuga en planta 0"),
    ("Fuga en P/O", "Fuga en planta 0"),
    ("Cargador P-1", "Cargador parking planta -1"),
    ("Sumidero P-2", "Sumidero parking planta -2"),
    ("Se abre P-1", "Se abre parking planta -1"),
    ("Cargador parking P-1", "Cargador parking planta -1"),
    ("Se abre Z6-1", "Se abre zona 6 planta -1"),
    ("Alumbrado Z0", "Alumbrado zona 0"),
    ("Se revisa planta -1.", "Se revisa planta -1."),
])
def test_floor_codes(raw, expected):
    assert expand_codes(raw) == expected


@pytest.mark.parametrize("raw, expected", [
    ("AGUASUR revisa el contador", "Aguasur revisa el contador"),
    ("Con DIGI en local 17", "Con Digi en local 17"),
    ("Telefonica en zona 4", "Telefónica en zona 4"),
    ("telefónica", "Telefónica"),
    ("Con ENDESA y SANEASUR", "Con Endesa y Saneasur"),
    ("Atis revisa cámaras", "ATIS revisa cámaras"),
    ("Endesas", "Endesas"),
])
def test_company_names(raw, expected):
    assert name_companies(raw) == expected


@pytest.mark.parametrize("raw, expected", [
    ("Conectando mq de aire", "Conectando máquinas de aire"),
    ("Conectando mg de aire", "Conectando máquinas de aire"),
    ("Conectando MQ de cobre", "Conectando máquinas de cobre"),
    ("Revisando cuadros eléctricos", "Revisando cuadros eléctricos"),
])
def test_mq_is_maquinas(raw, expected):
    assert expand_maintenance_terms(raw) == expected


@pytest.mark.parametrize("text, routine", [
    ("Conectando máquinas de aire", True),
    ("Conectando máquinas de aire.", True),
    ("Conectando mq de aire y de cobre", True),
    ("Revisando cuadros eléctricos", True),
    ("Revisión de cuadros eléctricos.", True),
    ("Revisando cuadros eléctricos, se detecta magnetotérmico saltado", False),
    ("Reparando máquina de aire de zona 4", False),
])
def test_the_daily_checks_are_routine(text, routine):
    assert is_routine_text(text) is routine


class TestDurationMeansParking:
    def test_a_duration_wins_over_the_model(self):
        assert decide(OTROS, "Desatoro en aseo (2H)") == PARKING
        assert decide(ELECTRICIDAD, "Cambio de tubos (1 hora)") == PARKING
        assert decide(ELECTRICIDAD, "Cambio de tubos (1,5 horas)") == PARKING

    def test_no_duration_no_change(self):
        assert decide(ELECTRICIDAD, "Cambio de tubos en zona 4") == ELECTRICIDAD


def read(*lines):
    return {"fecha": "02-09-2026", "operarios": [], "trabajos": list(lines)}


class TestParkingMark:
    def test_most_reads_saw_the_mark(self):
        page = consolidate([read("Desatoro en aseo [parking]"),
                            read("Desatoro en aseo [parking]"),
                            read("Desatoro en aseo")])
        entry = page["trabajos"][0]
        assert entry["text"] == "Desatoro en aseo"
        assert entry["parking_mark"] is True
        assert entry["confident"] is True, "the mark is not a disagreement about the words"

    def test_one_read_alone_is_not_enough(self):
        page = consolidate([read("Desatoro en aseo [parking]"),
                            read("Desatoro en aseo"), read("Desatoro en aseo")])
        assert page["trabajos"][0]["parking_mark"] is False

    def test_a_marked_line_is_filed_under_parking(self):
        page = {"tipo": "mantenimiento", "trabajos": [
            {"text": "Desatoro en aseo", "confident": True, "parking_mark": True},
            {"text": "Desatoro en aseo de zona 4", "confident": True},
        ]}
        apply_filter(page, None, blocks=[OTROS, OTROS])
        assert [e["bloque"] for e in page["trabajos"]] == [PARKING, OTROS]


def test_maintenance_lines_are_normalised_in_full():
    page = {"tipo": "mantenimiento", "trabajos": [
        {"text": "CONECTANDO MQ DE AIRE P/C", "confident": True},
        {"text": "Con AGUASUR en P-1 (2H)", "confident": True},
    ]}
    apply_filter(page, None, blocks=[OTROS, OTROS])
    texts = [e["text"] for e in page["trabajos"]]
    assert texts == ["Conectando máquinas de aire planta 1",
                     "Con Aguasur en parking planta -1"]
    assert page["trabajos"][1]["bloque"] == PARKING


@pytest.mark.parametrize("raw, expected", [
    ("Desatoro en aseo (2H).", "Desatoro en aseo."),
    ("Cambio de tubos (3 horas)", "Cambio de tubos"),
    ("Cambio de tubos (1,5 horas) en zona 4", "Cambio de tubos en zona 4"),
])
def test_the_duration_files_the_line_and_is_then_dropped(raw, expected):
    page = {"tipo": "mantenimiento", "trabajos": [{"text": raw, "confident": True}]}
    apply_filter(page, None, blocks=[ELECTRICIDAD])
    assert page["trabajos"][0]["text"] == expected
    assert page["trabajos"][0]["bloque"] == PARKING


def test_security_lines_keep_mg_alone():
    page = {"tipo": "seguridad", "trabajos": [{"text": "Se abre MG", "confident": True}]}
    apply_filter(page, None)
    assert "máquinas" not in page["trabajos"][0]["text"]


def prompt(name):
    with open(f"prompts/{name}", encoding="utf-8") as handle:
        return handle.read()


class TestPrompts:
    def test_transcription_reports_the_parking_mark(self):
        text = prompt("transcription.md")
        assert "[parking]" in text and "círculo con una X" in text and "rojo" in text

    def test_transcription_knows_the_maintenance_vocabulary(self):
        text = prompt("transcription.md")
        for word in ("mq (máquinas) de aire", "fosa séptica", "compactador", "fluxómetro",
                     "urinario", "tubería", "gotera", "Saneasur", "P/C", "P-1", "Z0"):
            assert word in text, word
        assert "mg (manguera)" not in text and "foso séptico" not in text

    def test_the_filter_leaves_floor_codes_to_the_system(self):
        text = prompt("filter_mantenimiento.md")
        assert "PC -> planta cero" not in text
        assert "mq -> máquinas" in text and "mg  -> manguera" not in text
        assert "P/C, P/A, P/0" in text and "TAL CUAL" in text

    def test_the_filter_files_durations_under_parking(self):
        text = prompt("filter_mantenimiento.md")
        bloque = text[text.index("BLOQUE:"):text.index("COHERENCIA:")]
        assert "(2H)" in bloque and "Parking" in bloque


def test_the_new_words_still_say_maintenance():
    from document_type import MANTENIMIENTO, classify
    assert classify("", ["Conectando mq de aire", "Revisión fosa séptica",
                         "Cambio de fluxómetro en urinario"]) == MANTENIMIENTO
