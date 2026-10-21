import pytest

from nettune.report.routine_rules import is_routine_text, strip_time_prefix, tidy_caps


@pytest.mark.parametrize("raw,expected", [
    ("07:00 COMIENZO EL SERVICIO", "COMIENZO EL SERVICIO"),
    ("21.45 Comienza el cierre parcial", "Comienza el cierre parcial"),
    ("  * 12:00 Se colocan pilonas", "Se colocan pilonas"),
    ("Se abre muelle", "Se abre muelle"),
    ("23:00 - Finalizo servicio", "Finalizo servicio"),
])
def test_time_prefix_is_removed(raw, expected):
    assert strip_time_prefix(raw) == expected


def test_a_number_that_is_not_a_time_survives():
    assert strip_time_prefix("Se abre zona 1, 2, 3") == "Se abre zona 1, 2, 3"


@pytest.mark.parametrize("raw,expected", [
    ("SE RETIRAN PILONAS.", "Se retiran pilonas."),
    ("SE ABREN TORREONES.", "Se abren torreones."),
    ("Se abre muelle", "Se abre muelle"),
])
def test_capitals_are_sentence_cased(raw, expected):
    assert tidy_caps(raw) == expected


def test_zone_codes_keep_their_case():
    assert "Z3" in tidy_caps("SE COLOCAN PILONAS Z3 Y Z1")
    assert "VS" in tidy_caps("RELEVO VS")


# --- routine, taken from the real SECUPOL sheets --------------------------


@pytest.mark.parametrize("text", [
    "07:00 COMIENZO EL SERVICIO",
    "Comienzo el servicio.",
    "Inicio servicio",
    "23:00 Finalizo servicio",
    "Finaliza el servicio.",
    "Relevo VS",
    "SE RETIRAN PILONAS.",
    "Se colocan pilonas Z3 y Z1.",
    "SE ABREN TORREONES.",
    "Se cierran torreones Z2 y Z3.",
    "Se abre muelle.",
    "Se cierra muelle.",
    "Se abre planta cero.",
    "Se abre zona 1, 2, 3.",
    "Se abren terrazas",
    "Se conectan rampas.",
    "Se conecta alumbrado de tarde.",
    "Se realizan rondas",
    "Salida de empleados por la puerta principal",
])
def test_shift_operation_is_routine(text):
    assert is_routine_text(text), text


# --- notable, must never be hidden ----------------------------------------


@pytest.mark.parametrize("text", [
    "Se llama la atencion a varios individuos por mal comportamiento en planta 0",
    "Se expulsa a un indigente por estar lavandose en los aseos de Z-6.",
    "Se recibe queja de posible pinchazo en las impulsoras, se indica olor",
    "Se observa que faltan dos mesas en terraza",
    "En ronda se detecta una puerta forzada en Z12",
    "Se avisa a la policia por una furgoneta aparcada en la acera",
    "Se informa de una averia en el iman de Z-2 del -1.",
    "Se contacta con M2 por una fuga de agua.",
    "Se produce un salto de alarma contraincendios sin novedad.",
])
def test_incidents_are_never_routine(text):
    assert not is_routine_text(text), text


def test_a_round_that_found_something_is_not_routine():
    assert is_routine_text("Se realizan rondas por todo el centro")
    assert not is_routine_text("Se realizan rondas y se detecta una puerta forzada")


def test_unknown_text_is_not_assumed_routine():
    assert not is_routine_text("Algo que no se entiende")
    assert not is_routine_text("")


@pytest.mark.parametrize("text", [
    "Apertura muelle",
    "Cierre muelle",
    "Alumbrado tarde",
    "Alumbrado noche",
    "Alumbrado urbanizacion",
    "Apertura acceso de personal",
    "Apertura accesos gimnasio",
    "Se cierran pilonas",
    "Se retiran accesos pilonas",
    "Se comienza a cerrar planta 0",
    "Comienza el cierre parcial de planta 0",
    "Se revisan las zonas Z1 y Z3",
    "Se revisa el alumbrado exterior",
])
def test_noun_phrase_shift_operation_is_routine(text):
    assert is_routine_text(text), text


@pytest.mark.parametrize("text", [
    "Se observa un camion de papel cerca del acceso de entrada",
    "Se avisa a limpieza para recoger agua",
    "Se informa a H-2 de la apertura del ascensor prorrogada, se guardan imagenes",
    "Se llama la atencion a una persona por patinete",
])
def test_events_still_survive_the_wider_rules(text):
    assert not is_routine_text(text), text


@pytest.mark.parametrize("text", [
    "Se abren Z-1 y Z-3.", "Se cierra Z-2.", "Se abre Z-2.", "Se cierran Z1 y Z-3.",
    "Se cierra el centro.", "Se revisa el centro.", "Fin de servicio.",
    "Finazo del servicio.", "Se abre aseos del personal.",
    "Se apagan las luces de la fachada.", "No hay novedades.",
    "Se realizan varias revisiones por el centro.",
    "Se realiza control de acceso para entrar y salir.", "Se abre P1.",
])
def test_more_shift_operation_from_the_real_sheets(text):
    assert is_routine_text(text), text


@pytest.mark.parametrize("text", [
    "Se produce un cierre sin novedad.",
    "Nuevo turno sin incidencias hasta el momento",
    "Se realizan rondas sin novedad",
    "No hay novedades.",
    "Sin incidencias",
])
def test_nothing_happened_is_routine_wherever_the_phrase_sits(text):
    assert is_routine_text(text), text


def test_an_incident_that_ends_sin_novedad_is_still_an_event():
    """'Se acude a Burger King por un cliente dando voces, sin novedad.'"""
    assert not is_routine_text(
        "Se acude a Burger King por un cliente dando voces, sin novedad."
    )


@pytest.mark.parametrize("text", ["22:10 -", "23:40 -", "02:05 S.A. ...", "", "   ", "-"])
def test_lines_that_lost_their_words_are_noise(text):
    from nettune.report.routine_rules import is_noise
    assert is_noise(text), text


@pytest.mark.parametrize("text", [
    "Se cierra el corredor.",
    "Se retiran pilonas.",
    "Se llama la atencion a una persona",
])
def test_real_entries_are_not_noise(text):
    from nettune.report.routine_rules import is_noise
    assert not is_noise(text), text


@pytest.mark.parametrize("text", [
    "Se abre el muelle para retirar la compactadora.",
    "Se abre el muelle para una empresa de vinilos.",
    "Se abre el cuarto de la fosa septica para la obra de los cargadores.",
])
def test_opening_for_a_reason_is_an_event(text):
    """The routine version names no purpose: 'Se abre muelle'."""
    assert not is_routine_text(text), text


def test_the_plain_opening_is_still_routine():
    assert is_routine_text("Se abre muelle")
    assert is_routine_text("Se cierra muelle.")


@pytest.mark.parametrize("text", [
    "Se produce un seismo sin novedad.",
    "Se produce un salto de alarma contraincendios sin novedad.",
    "Salta la alarma de incendios en Z-2 y se verifica que todo esta en orden.",
])
def test_an_occurrence_is_an_event_even_when_it_did_no_damage(text):
    """'sin novedad' describes the outcome, not the absence of an occurrence."""
    assert not is_routine_text(text), text


@pytest.mark.parametrize("text", [
    "Se realizan rondas sin novedad",
    "Nuevo turno sin incidencias hasta el momento",
    "No hay novedades.",
])
def test_nothing_happening_is_still_routine(text):
    assert is_routine_text(text), text


@pytest.mark.parametrize("raw,expected", [
    ("21.45h Cierre de pilonas", "Cierre de pilonas"),
    ("20:00h Conexion del alumbrado", "Conexion del alumbrado"),
    ("19:30 h Apertura del acceso", "Apertura del acceso"),
    # Only the digits were read; the lone h is not part of the sentence.
    ("h Cierre de pilonas de zona 3", "Cierre de pilonas de zona 3"),
])
def test_the_h_written_after_a_time_goes_with_it(raw, expected):
    assert strip_time_prefix(raw) == expected


@pytest.mark.parametrize("text", [
    "Hora de entrada registrada",
    "Hay un tubo descolgado en zona 6",
])
def test_a_word_starting_with_h_survives(text):
    assert strip_time_prefix(text) == text


@pytest.mark.parametrize("text", [
    "21.45h Cierre de pilonas",
    "h Conexion del alumbrado de noche",
    "20:00h Apertura del acceso nocturno",
])
def test_those_lines_are_then_recognised_as_routine(text):
    assert is_routine_text(text), text
