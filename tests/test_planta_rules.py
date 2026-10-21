"""How a floor is written, and what to do when it was read as nonsense."""

import pytest

from routine_rules import expand_codes, invalid_plantas, is_incoherent, is_routine_text


class TestPlantaWording:
    @pytest.mark.parametrize("raw,expected", [
        # The named floors are numbered: calle 1, baja 0, alta 2.
        ("Cartel en Pt calle.", "Cartel en planta 1."),
        ("Cartel en planta calle.", "Cartel en planta 1."),
        ("Ruido en planta baja.", "Ruido en planta 0."),
        ("Local en planta alta.", "Local en planta 2."),
        ("Aseos en planta cero.", "Aseos en planta 0."),
        ("Se revisa Pt 1.", "Se revisa planta 1."),
        # The hyphen is a separator here, as it already is for "P-1".
        ("Se revisa Pt-2.", "Se revisa planta 2."),
        ("Se coloca cartel de 3-7 Pt calle.", "Se coloca cartel de 3-7 planta 1."),
    ])
    def test_pt_is_written_as_planta(self, raw, expected):
        assert expand_codes(raw) == expected

    def test_the_existing_codes_are_unchanged(self):
        assert expand_codes("Z3 y P1") == "zona 3 y planta 1"
        assert expand_codes("P\u00d8") == "planta 0"
        assert expand_codes("PA y PB") == "planta 2 y planta 0"

    def test_pc_is_planta_calle(self):
        """PC appears 101 times across the 35 memorias; it is planta calle."""
        assert expand_codes("Se llama la atenci\u00f3n en PC") == (
            "Se llama la atenci\u00f3n en planta 1"
        )

    def test_planta_cero_is_written_as_a_number(self):
        assert expand_codes("Ruido en planta cero.") == "Ruido en planta 0."


class TestInvalidPlanta:
    """Only -2, -1, 0, 1 and 2 exist in this building."""

    @pytest.mark.parametrize("text", [
        "Se llama la atención en planta P.",
        "Ruido en planta A.",
        "Se revisa planta 7.",
    ])
    def test_a_floor_that_does_not_exist_is_reported(self, text):
        assert invalid_plantas(text)

    @pytest.mark.parametrize("text", [
        "Se llama la atención en planta 0.",
        "Se revisa planta -1.",
        "Se revisa planta 2 y planta -2.",
        # Written floors are numbered before this check ever runs.
        "Se abre la planta 0.",
        "Nada que ver aquí.",
    ])
    def test_a_real_floor_is_not_reported(self, text):
        assert not invalid_plantas(text)


class TestIncoherent:
    @pytest.mark.parametrize("text", [
        "Se procede.",
        "Se incorpora el vigilante. Se procede.",
        "Se realiza.",
    ])
    def test_a_dangling_fragment_is_incoherent(self, text):
        assert is_incoherent(text)

    @pytest.mark.parametrize("text", [
        "Se procede a cerrar el centro.",
        "Se llama la atención a dos personas.",
        "Schindler repara la avería del ascensor de zona 4.",
    ])
    def test_a_finished_sentence_is_not(self, text):
        assert not is_incoherent(text)

    def test_an_impossible_floor_makes_the_entry_incoherent(self):
        assert is_incoherent("Se llama la atención en planta P.")


class TestVigilante:
    @pytest.mark.parametrize("text", [
        "Se incorpora el vigilante.",
        "Se incorpora vigilante",
        "Incorporación del vigilante de seguridad.",
    ])
    def test_the_guard_arriving_is_a_shift_operation(self, text):
        assert is_routine_text(text)
