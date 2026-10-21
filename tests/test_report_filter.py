"""Stage 2: tidy the wording and redact names, without losing information.

The filter runs on text several OCR passes already agreed on, so its job is
cosmetic. It must never drop, merge, reorder or invent entries, and it must
never launder away the uncertainty flags stage 1 produced -- an entry the OCR
passes disagreed on is still uncertain after being tidied up.
"""


from filtering_agents import apply_filter, redact_operarios


def page(entries=None, operarios=("A. Ejemplo",)):
    if entries is None:
        entries = [
            {"text": "Revisando cuadro eléctrico,", "confident": True, "variants": []},
            {"text": "Con la obra de cargadores en PK 2-6 ext. (1H)", "confident": False,
             "variants": ["... cargadores ...", "... cargadero ..."]},
        ]
    return {
        "titulo": "FICHA DIARIA DE TRABAJO",
        "fecha": "02-07-2026",
        "fecha_confident": True,
        "operarios": list(operarios),
        "operarios_confident": True,
        "trabajos": entries,
    }


# --- applying a good filter result ----------------------------------------


def test_cleaned_text_replaces_the_literal_text():
    out = apply_filter(page(), ["Revisando cuadros eléctricos",
                                "Obra de cargadores en parking 2-6 exterior (1 hora)"])
    assert out["trabajos"][0]["text"] == "Revisando cuadros eléctricos"
    assert "parking" in out["trabajos"][1]["text"]


def test_uncertainty_survives_the_cleanup():
    """Tidying wording must not make a doubtful entry look confirmed."""
    out = apply_filter(page(), ["Revisando cuadros eléctricos",
                                "Obra de cargadores en parking 2-6 exterior (1 hora)"])
    assert out["trabajos"][0]["confident"] is True
    assert out["trabajos"][1]["confident"] is False
    assert out["trabajos"][1]["variants"], "alternative readings must be kept"


def test_the_original_reading_is_preserved_for_reference():
    out = apply_filter(page(), ["Revisando cuadros eléctricos", "Obra de cargadores"])
    assert out["trabajos"][0]["literal"] == "Revisando cuadro eléctrico,"


def test_entry_order_is_preserved():
    out = apply_filter(page(), ["primero", "segundo"])
    assert [t["text"] for t in out["trabajos"]] == ["primero", "segundo"]


# --- refusing a bad filter result -----------------------------------------


def test_a_result_with_fewer_entries_is_rejected():
    """Dropping a line is data loss; keep the literal text instead."""
    original = page()
    out = apply_filter(original, ["solo una"])
    assert len(out["trabajos"]) == 2
    assert out["trabajos"][0]["text"] == "Revisando cuadro eléctrico,"


def test_a_result_with_extra_entries_is_rejected():
    out = apply_filter(page(), ["una", "dos", "tres"])
    assert len(out["trabajos"]) == 2
    assert out["trabajos"][1]["text"].startswith("Con la obra")


def test_an_empty_result_is_rejected():
    out = apply_filter(page(), [])
    assert len(out["trabajos"]) == 2


def test_a_blank_cleaned_entry_falls_back_to_the_literal():
    out = apply_filter(page(), ["", "Obra de cargadores"])
    assert out["trabajos"][0]["text"] == "Revisando cuadro eléctrico,"


def test_a_page_with_no_entries_is_handled():
    out = apply_filter(page(entries=[]), [])
    assert out["trabajos"] == []


# --- redaction ------------------------------------------------------------


def test_operarios_are_redacted():
    out = redact_operarios(page(), enabled=True)
    assert out["operarios"] == []
    assert out["operarios_redacted"] is True


def test_redaction_can_be_turned_off():
    out = redact_operarios(page(), enabled=False)
    assert out["operarios"] == ["A. Ejemplo"]
    assert not out.get("operarios_redacted")


def test_redaction_does_not_touch_the_date():
    """The date identifies the sheet; it is never redacted."""
    out = redact_operarios(page(), enabled=True)
    assert out["fecha"] == "02-07-2026"


def test_redaction_leaves_work_entries_alone():
    out = redact_operarios(page(), enabled=True)
    assert "cargadores" in out["trabajos"][1]["text"]


# --- per-type routing -----------------------------------------------------


def test_maintenance_pages_use_the_maintenance_prompt():
    from filtering_agents import prompt_for

    assert prompt_for("mantenimiento") == "filter_mantenimiento.md"


def test_security_pages_use_the_security_prompt():
    from filtering_agents import prompt_for

    assert prompt_for("seguridad") == "filter_seguridad.md"


def test_an_unknown_type_falls_back_to_maintenance_wording():
    """Maintenance is the more conservative of the two: it rewrites less."""
    from filtering_agents import prompt_for

    assert prompt_for("desconocido") == "filter_mantenimiento.md"
    assert prompt_for(None) == "filter_mantenimiento.md"


def test_both_prompt_files_exist():
    import os

    from filtering_agents import prompt_for

    for kind in ("mantenimiento", "seguridad"):
        assert os.path.exists(os.path.join("prompts", prompt_for(kind)))


# --- the log's own words for people ---------------------------------------


def test_a_rewrite_that_turns_jovenes_into_personas_is_not_used():
    entries = [{"text": "Se llama la atención a unos jóvenes en Z4", "confident": True},
               {"text": "dos chicas en patinete por Z6", "confident": True},
               {"text": "quito pilonas Z1", "confident": True}]
    out = apply_filter(page(entries), ["Se llama la atención a unas personas en Z4",
                                       "Dos personas en patinete por Z6",
                                       "Se quitan pilonas Z1"])
    texts = [e["text"] for e in out["trabajos"]]
    assert "jóvenes" in texts[0] and "persona" not in texts[0]
    assert "chicas" in texts[1]
    # Every other rewrite is still used.
    assert texts[2] == "Se quitan pilonas zona 1"


def test_removing_a_name_is_still_allowed():
    entries = [{"text": "Se expulsa a D. Ejemplo por fumar", "confident": True}]
    out = apply_filter(page(entries), ["Se expulsa a una persona por fumar"])
    assert out["trabajos"][0]["text"] == "Se expulsa a una persona por fumar"


def test_the_prompt_keeps_how_the_log_describes_people():
    with open("prompts/filter_seguridad.md", encoding="utf-8") as handle:
        prompt = handle.read()
    assert '"una chica en patinete" -> "una persona en patinete"' not in prompt
    assert "unos jóvenes" in prompt
