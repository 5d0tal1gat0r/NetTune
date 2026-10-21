"""The tenant directory in the template is the authority on local names."""

import os

import pytest

from nettune.report.locales import correct_names, local_numbers, tenant_names

TEMPLATE = "templates/MEMORIA.docx"
pytestmark = pytest.mark.skipif(not os.path.exists(TEMPLATE), reason="template absent")


class TestDirectory:
    def test_the_tenants_are_read_from_the_template(self):
        names = tenant_names(TEMPLATE)
        assert "Mae Vest" in names
        assert "Park Line" in names
        assert "Los Diamantes" in names
        assert len(names) > 50

    def test_the_local_numbers_are_read_too(self):
        numbers = local_numbers(TEMPLATE)
        assert "3" in numbers and "14" in numbers
        # Compound units are listed as one local: 9/13, 15/16, 10/11/12.
        assert any("/" in n for n in numbers)


class TestCorrection:
    @pytest.mark.parametrize("raw,expected", [
        ('Apertura de torreón zona 4, a "MAC VEST" (gerencia).',
         'Apertura de torreón zona 4, a "Mae Vest" (gerencia).'),
        ("Parkline estaciona su vehículo en zona de carga.",
         "Park Line estaciona su vehículo en zona de carga."),
        ("Se llama la atención a personal de MAC-VEST.",
         "Se llama la atención a personal de Mae Vest."),
    ])
    def test_a_misread_tenant_is_written_as_the_directory_writes_it(self, raw, expected):
        assert correct_names(raw, TEMPLATE) == expected

    def test_a_name_already_right_is_untouched(self):
        text = "Se presenta el técnico de Los Diamantes."
        assert correct_names(text, TEMPLATE) == text

    @pytest.mark.parametrize("text", [
        "Se llama la atención a dos personas.",
        "Se abre el muelle para la descarga.",
        "Corte de carril grande en zona 3.",
    ])
    def test_ordinary_words_are_never_turned_into_a_tenant(self, text):
        assert correct_names(text, TEMPLATE) == text

    def test_a_word_too_far_from_any_tenant_is_left_alone(self):
        """Correcting only near misses: a real misread must stay visible."""
        text = "Se abre el torreón a Zzzzzzz."
        assert correct_names(text, TEMPLATE) == text


class TestKnownMisreads:
    @pytest.mark.parametrize("raw,expected", [
        ("Salida clientes Posier", "Salida clientes Poker"),
        ("Avisan del posier para expulsar a un cliente", "Avisan del Poker para expulsar a un cliente"),
    ])
    def test_posier_is_the_poker(self, raw, expected):
        assert correct_names(raw, TEMPLATE) == expected

    def test_only_the_whole_word(self):
        assert correct_names("Posiera", TEMPLATE) == "Posiera"

    def test_stored_lines_are_corrected_but_not_hand_edited_ones(self, tmp_path):
        import importlib.util

        from nettune.report.entry_store import EntryStore
        from nettune.report.memoria import SEGURIDAD_BLOCK

        spec = importlib.util.spec_from_file_location("correct_names_tool",
                                                      "tools/correct_names.py")
        tool = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(tool)
        with EntryStore(str(tmp_path / "e.sqlite3")) as store:
            store.add("2026", "SEPTIEMBRE", SEGURIDAD_BLOCK, [
                {"text": "Avisan del Posier por un cliente", "confident": False},
                {"text": "Llaman del Posier"},
            ], source="scan.pdf")
            ids = [e["id"] for e in store.month_entries("2026", "SEPTIEMBRE")]
            store.edit_entry(ids[1], "Llaman del Posier")
            changes = tool.plan(store, "2026", "SEPTIEMBRE", TEMPLATE)
            assert [c for _, c in changes] == ["Avisan del Poker por un cliente"]
            assert store.rewrite_entry(changes[0][0]["id"], changes[0][1])
            entry = store.month_entries("2026", "SEPTIEMBRE")[0]
            # Still to be read by a person: a rule fixed the name, not them.
            assert entry["flagged"] and not entry["hand_edited"]
