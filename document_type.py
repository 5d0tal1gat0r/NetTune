"""Tells a mantenimiento sheet from a seguridad sheet.

The two use different vocabulary and are filed differently, so the type decides
which filter prompt runs. The model is asked to label the page, but its answer
is checked against the page's own vocabulary: a label is cheap to get wrong and
expensive to act on, and routing a sheet to the wrong filter would redact or
expand the wrong things.
"""

import re
import unicodedata

MANTENIMIENTO = "mantenimiento"
SEGURIDAD = "seguridad"
UNKNOWN = "desconocido"

# How much one vocabulary must outweigh the other to overrule the model.
_DECISIVE = 3


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", str(text or ""))
    return "".join(c for c in text if not unicodedata.combining(c)).lower()


def normalise(raw) -> str:
    """Map whatever the model called the type onto a known value."""
    if not isinstance(raw, str):
        return UNKNOWN
    folded = _fold(raw)
    if not folded.strip():
        return UNKNOWN
    if re.search(r"manteni|mantemi|obra|tecnic", folded):
        return MANTENIMIENTO
    if re.search(r"segurida|vigilan|porteri|servicio de seguridad", folded):
        return SEGURIDAD
    return UNKNOWN


# Words that only really appear on one kind of sheet. Deliberately excludes
# terms both use (muelle, alumbrado, planta, revision, cierre, apertura).
_MANTENIMIENTO_TERMS = (
    "cuadros electricos", "cuadro electrico", "mg de aire", "mg de cobre",
    "manguera", "grupo electrogeno", "transformador", "cargadores",
    "aire acondicionado", "foso septico", "sumidero", "escalera mecanica",
    "manivela", "extintores", "endesa", "aguasur", "telefonia", "fachada",
    "desatoro", "contador", "riego", "parking",
    "mq de aire", "maquinas de aire", "fosa septica", "fluxometro", "urinario",
    "compactador", "saneasur",
)
_SEGURIDAD_TERMS = (
    "inicio del servicio", "comienzo del servicio", "finaliza el servicio",
    "finalizacion del servicio", "pilonas", "torreon", "torreones", "ronda",
    "rondas", "porton", "rampas", "accesos", "terraza", "llama la atencion",
    "se llama la atencion", "queja", "patinete", "ascensor", "aseos",
    "salida de empleados", "sistemas de seguridad",
)


def _score(text: str) -> tuple[int, int]:
    folded = _fold(text)
    mantenimiento = sum(1 for t in _MANTENIMIENTO_TERMS if t in folded)
    seguridad = sum(1 for t in _SEGURIDAD_TERMS if t in folded)
    # Zone codes (Z1, Z6-1, Z27) are security; bay codes (7-4, P-1) maintenance.
    seguridad += len(re.findall(r"\bz\s?\d{1,2}\b", folded))
    mantenimiento += len(re.findall(r"\bp-?\d\b|\b\d-\d\b", folded))
    return mantenimiento, seguridad


def classify(titulo: str, trabajos: list[str]) -> str:
    """Identify the type from the page's own words, or UNKNOWN."""
    title = _fold(titulo)
    if "manteni" in title:
        return MANTENIMIENTO
    if "segurida" in title or "vigilan" in title:
        return SEGURIDAD

    mantenimiento, seguridad = _score(" ".join(trabajos or []))
    if mantenimiento > seguridad:
        return MANTENIMIENTO
    if seguridad > mantenimiento:
        return SEGURIDAD
    return UNKNOWN


def decide(model_answer, titulo: str, trabajos: list[str]) -> str:
    """Final type: the model's label unless the page's vocabulary contradicts it."""
    from_content = classify(titulo, trabajos)
    from_model = normalise(model_answer)

    if from_content == UNKNOWN:
        return from_model
    if from_model in (UNKNOWN, from_content):
        return from_content

    # They disagree. Trust the page only when its vocabulary is decisive.
    mantenimiento, seguridad = _score(" ".join(trabajos or []))
    if abs(mantenimiento - seguridad) >= _DECISIVE:
        return from_content
    return from_model
