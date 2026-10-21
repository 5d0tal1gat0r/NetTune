import pytest

from transcription_service import RefusalError, is_refusal, parse_reading


@pytest.mark.parametrize("text", [
    "I'm sorry, I can't assist with that.",
    "I'm sorry, but I can't help with that request.",
    "Lo siento, no puedo ayudar con eso.",
    "I cannot assist with transcribing this image.",
    "Sorry, I can't provide that.",
    "I'm unable to transcribe handwritten text from images.",
])
def test_detects_refusals(text):
    assert is_refusal(text)


@pytest.mark.parametrize("text", [
    '{"titulo": "FICHA DIARIA", "fecha": "02-07-2026", "trabajos": ["Conectando mg de aire"]}',
    '{"fecha": null, "trabajos": []}',
])
def test_real_output_is_not_a_refusal(text):
    assert not is_refusal(text)


def test_empty_output_counts_as_a_refusal():
    """A blank reply is not a blank page; it is a failed call."""
    assert is_refusal("")
    assert is_refusal("   ")


# --- parsing --------------------------------------------------------------


def test_parses_plain_json():
    d = parse_reading('{"fecha":"02-07-2026","trabajos":["uno"],"operarios":["X"]}')
    assert d["fecha"] == "02-07-2026"
    assert d["trabajos"] == ["uno"]


def test_parses_json_in_a_fenced_block():
    d = parse_reading('```json\n{"fecha":"02-07-2026","trabajos":[]}\n```')
    assert d["fecha"] == "02-07-2026"


def test_parses_json_with_surrounding_prose():
    d = parse_reading('Aquí tienes:\n{"fecha":"02-07-2026","trabajos":[]}\nEso es todo.')
    assert d["fecha"] == "02-07-2026"


def test_refusal_raises_rather_than_parsing():
    with pytest.raises(RefusalError):
        parse_reading("I'm sorry, I can't assist with that.")


def test_unparseable_output_raises():
    with pytest.raises(RefusalError):
        parse_reading("esto no es json en absoluto")


def test_missing_keys_are_filled_with_safe_defaults():
    d = parse_reading('{"fecha":"02-07-2026"}')
    assert d["trabajos"] == []
    assert d["operarios"] == []
    assert d["titulo"] is None
    assert d["tipo"] is None


def test_the_document_type_is_carried_through():
    d = parse_reading('{"tipo":"seguridad","fecha":null,"trabajos":[]}')
    assert d["tipo"] == "seguridad"


def test_trabajos_given_as_a_string_becomes_a_list():
    d = parse_reading('{"fecha":null,"trabajos":"una sola linea"}')
    assert d["trabajos"] == ["una sola linea"]
