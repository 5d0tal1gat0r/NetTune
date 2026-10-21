"""Deterministic cleanup and routine detection for security entries.

Two problems the model cannot be relied on to solve:

* The sheets record a time against each line ("07:00 COMIENZO EL SERVICIO") and
  write many lines in capitals. The author's memoria has neither.
* Almost every entry on a handwritten security sheet comes back flagged,
  because three reading passes rarely agree word for word. The rule "never hide
  an entry we are unsure about" then hides nothing at all, and the memoria
  fills with openings and closings.

So routine detection also runs on the text itself. A line that plainly says the
pilonas were removed is routine whether or not the passes agreed on every word;
anything describing an incident is never matched by these patterns.
"""

import re
import unicodedata

_TIME_PREFIX = re.compile("^\\s*\\d{1,2}[:.]\\d{2}\\s*[hH]?\\s*[-\u2013]?\\s*")
_BULLET_PREFIX = re.compile(r"^[\s*\-•·.]+")


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", str(text or ""))
    return "".join(c for c in text if not unicodedata.combining(c)).lower()


_ORPHAN_H = re.compile(r"^[hH]\s+(?=[A-Za-z\u00c0-\u017f])")


def strip_time_prefix(text: str) -> str:
    """Remove a leading clock time. The memoria records what, not when.

    Handles the "21.45h" form the vigilantes write, and the lone "h" left
    behind when only the digits were read.
    """
    text = _TIME_PREFIX.sub("", _BULLET_PREFIX.sub("", str(text or "")))
    return _ORPHAN_H.sub("", text).strip()


# Zone and post codes keep their case: Z3, Z6-1, PO, VS.
_CODE = re.compile("[A-Z\u00d1]{1,2}[-\u2013]?[0-9\u00d8O]{1,3}([-\u2013][0-9]{1,2})?")

# The vigilantes write Z3 and P1; the memoria says "zona 3" and "planta 1".
_ZONE_PLANT = re.compile(r"(?<!zona )\bZ\s?-?\s?(\d{1,2})\s?-\s?(\d)\b", re.I)
_ZONE_CODE = re.compile(r"\bZ\s?-?\s?(\d{1,2})\b", re.I)
_PLANT_CODE = re.compile(r"\bP\s?-?\s?(\d{1,2})\b", re.I)
# L-40, L40 and L-51B are units: the memoria says "local 40", "local 51B".
_LOCAL_CODE = re.compile(r"\bL\s?-?\s?(\d{1,3})([A-Za-z]?)\b", re.I)

# Radio callsigns for staff: M1/M2/M3 are mantenimiento, A1/A2/A3 gerencia.
# The number identifies a person, so it is dropped with the other names.
_CALLSIGN = re.compile(r"\b([MA])\s?-?\s?([123])\b")
_CALLSIGN_ROLE = {"M": "mantenimiento", "A": "gerencia"}
_PLANT_WORD = {
    # The named floors, as the author uses them: calle is 1, baja is 0,
    # alta is 2, and cero is 0. PC is planta calle, so it is planta 1.
    "p\u00f8": "planta 0", "po": "planta 0", "pc": "planta 1",
    "pa": "planta 2", "pb": "planta 0",
}

# "Pt" is another way the vigilantes write planta. The named floors are
# numbered: planta calle is 1, planta baja is 0, planta alta is 2.
_PT_CODE = re.compile(r"\bPt\s?-?\s?(\d{1,2})\b", re.I)
_PT_WORD = re.compile(r"\bPt\b", re.I)
# "PL", "PL." and "P.L." are a third way of writing planta, seen across the
# September batch: "zona 6 PL. 8", "zona comun de P.L. 0".
# The floor may be written as a digit or as the slashed zero: "PL. 8",
# "pl\u00f8". Both name a floor; the slashed zero is nought.
_PL_CODE = re.compile(r"\bP\.?\s?L\.?\s*(-?\d{1,2}|[\u00d8\u00f8])", re.I)
_PL_WORD = re.compile(r"\bP\.?\s?L\.?(?![A-Za-z0-9])", re.I)
_NAMED_PLANTA = re.compile(r"\bplanta\s+(calle|baja|alta|cero)\b", re.I)
_NAMED_PLANTA_NUMBER = {"calle": "1", "baja": "0", "alta": "2", "cero": "0"}

# The building has these floors and no others. Anything else is a misread,
# and there is no way to tell which floor was meant, so the entry is flagged
# rather than guessed at.
VALID_PLANTAS = frozenset({"-2", "-1", "0", "1", "2"})

# P-1 and P-2 are the two parking floors underground, on both kinds of sheet.
# Read as "planta 1" the minus was lost and the line stopped being Parking.
_PARKING_FLOOR = re.compile(r"\bP\s?-\s?([12])\b")
# P/C, P/A and P/0 name the floors by letter: planta calle is 1, planta alta
# is 2 and planta baja (written P/0, P/Ø or P/O) is 0. Either case: a line
# written in capitals is lowercased (tidy_caps) before this runs.
_SLASH_FLOOR = re.compile("\\b[Pp]\\s?/\\s?([CcAa0Oo\u00d8\u00f8])(?![A-Za-z0-9])")
_SLASH_FLOOR_NUMBER = {"c": "1", "a": "2"}

# Companies working on maintenance, written as the author writes them: names,
# except ATIS, an acronym. The sheets often have them in capitals.
_COMPANIES = {
    "aguasur": "Aguasur", "digi": "Digi", "telefonica": "Telefónica",
    "telefónica": "Telefónica", "endesa": "Endesa", "saneasur": "Saneasur",
    "atis": "ATIS",
}
_COMPANY = re.compile(r"\b(aguasur|digi|telef[oó]nica|endesa|saneasur|atis)\b", re.I)


def name_companies(text: str) -> str:
    """AGUASUR -> Aguasur, TELEFONICA -> Telefónica, Atis -> ATIS."""
    return _COMPANY.sub(lambda m: _COMPANIES[m.group(1).lower()], text)


# "mq" is máquinas, as in "Conectando mq de aire"; "mg" is how it reads when
# the q's tail is lost. Maintenance sheets only.
_MAQUINAS = re.compile(r"\b(mq|mg)\b", re.I)


def expand_maintenance_terms(text: str) -> str:
    """Conectando mq de aire -> Conectando máquinas de aire."""
    return _MAQUINAS.sub("máquinas", text)
_PLANTA_VALUE = re.compile(r"\bplanta\s+(-?\w+)", re.I)
_PLANTA_WORDS = frozenset({"primera", "segunda"})


def expand_codes(text: str) -> str:
    """Write zone and plant codes the way the memoria does.

    Z3 -> zona 3, P1 -> planta 1, Z6-1 -> zona 6 planta -1, L-40 -> local 40, L-51B -> local 51B,
    P-1 -> parking planta -1, P/C -> planta 1, P/A -> planta 2, P/0 -> planta 0,
    M2 -> mantenimiento, A1 -> gerencia, Pt -> planta, and the named floors by
    number: planta calle -> planta 1, planta baja and planta cero -> planta 0,
    planta alta -> planta 2, PC (planta calle) -> planta 1, PL -> planta.
    Bay and door codes written as two numbers ("7-4", "2-6") are left alone:
    they are not zones.
    """
    text = _CALLSIGN.sub(lambda m: _CALLSIGN_ROLE[m.group(1).upper()], text)
    text = _SLASH_FLOOR.sub(
        lambda m: "planta " + _SLASH_FLOOR_NUMBER.get(m.group(1).lower(), "0"), text
    )
    text = _PARKING_FLOOR.sub(lambda m: f"parking planta -{m.group(1)}", text)
    text = _LOCAL_CODE.sub(lambda m: f"local {m.group(1)}{m.group(2).upper()}", text)
    text = _ZONE_PLANT.sub(lambda m: f"zona {m.group(1)} planta -{m.group(2)}", text)
    text = _ZONE_CODE.sub(lambda m: f"zona {m.group(1)}", text)
    text = _PL_CODE.sub(
        lambda m: "planta " + ("0" if m.group(1) in "\u00d8\u00f8" else m.group(1)),
        text,
    )
    text = _PT_CODE.sub(lambda m: f"planta {m.group(1)}", text)
    text = _PLANT_CODE.sub(lambda m: f"planta {m.group(1)}", text)
    text = _PT_WORD.sub("planta", text)
    text = _PL_WORD.sub("planta", text)
    text = _NAMED_PLANTA.sub(
        lambda m: f"planta {_NAMED_PLANTA_NUMBER[m.group(1).lower()]}", text
    )

    def word(match):
        return _PLANT_WORD.get(match.group(0).lower(), match.group(0))

    text = re.sub(r"\bP([AaBbCc]\b|[Oo\u00d8](?![A-Za-z0-9]))", word, text)
    # A code the model already expanded leaves "zona zona 3"; collapse it.
    text = re.sub(r"\b(zona|planta|local|parking)\s+\1\b", r"\1", text, flags=re.I)
    text = re.sub(r"\b(zona|planta|local)\s+(zona|planta|local)\s", r"\2 ", text, flags=re.I)
    return re.sub(r"\s{2,}", " ", text).strip()


def invalid_plantas(text: str) -> list[str]:
    """Floors named in *text* that this building does not have.

    The vigilante writes a digit; "planta P" is the reader failing to read it.
    Which floor was meant cannot be recovered from the text, so the entry is
    flagged for a human rather than guessed at.
    """
    found = []
    for value in _PLANTA_VALUE.findall(text):
        if value.lower() in _PLANTA_WORDS or value in VALID_PLANTAS:
            continue
        found.append(value)
    return found


def is_incoherent(text: str) -> bool:
    """True when the line does not read as something a vigilante wrote.

    Catches what a reader produces when it loses the middle of a sentence:
    a bare "Se procede." with nothing to proceed to, or a floor that does not
    exist. The model judges the rest -- this is the backstop for when it does
    not answer or waves a line through.
    """
    if invalid_plantas(text):
        return True
    for sentence in re.split(r"(?<=[.!?])\s+", text.strip()):
        stripped = sentence.strip(" .!?")
        if not stripped:
            continue
        if _DANGLING.fullmatch(_fold(stripped)):
            return True
    return False


def tidy_caps(text: str) -> str:
    """Sentence-case a line written in capitals, keeping zone codes intact."""
    text = text.strip()
    letters = [c for c in text if c.isalpha()]
    if not letters or sum(c.isupper() for c in letters) / len(letters) < 0.8:
        return text
    out = []
    for word in text.split(" "):
        if _CODE.fullmatch(word) or word in ("VS", "CCTV"):
            out.append(word)
        else:
            out.append(word.lower())
    sentence = " ".join(out)
    return sentence[:1].upper() + sentence[1:] if sentence else sentence


# Lines that are the ordinary running of a shift. Deliberately narrow: each
# needs an action verb AND a routine object, so an incident never matches.
_ZONE = r"(zonas?|z\s?-?\s?\d{1,2}|planta|plantas|p\s?-?\s?\d|pc|pa|p0|po)"
_OPENABLE = (
    r"(torreon|torreones|acceso|accesos|puerta|puertas|porton|portones|terraza|"
    r"terrazas|muelle|persiana|persianas|aseos?|gimnasio|centro|rampa|rampas|"
    r"cortina|cortinas|" + _ZONE + r")"
)

_ROUTINE = (
    # The two daily checks on a maintenance sheet, and nothing added to them:
    # "Revisando cuadros eléctricos, se detecta ..." is work, not the check.
    r"^(conectando|conectar|se conectan?|conexion de)\s+(las?\s+|los\s+)?"
    r"(maquinas?|mq|mg|mangueras?)\s+de\s+(aire|cobre)"
    r"(\s+y\s+(de\s+)?(aire|cobre))?\s*\.?$",
    r"^(revisando|revisar|revision de|se revisan?)\s+(los\s+)?"
    r"cuadros?\s+electricos?\s*\.?$",
    r"\b(comienzo|comienza|inicio|inicia)\b.*\bservicio\b",
    r"\b(finaliz\w*|finaz\w*|termin\w*|fin)\b.*\bservicio\b",
    r"^relevo\b",
    r"\b(se )?(retiran|quitan|colocan|ponen|cierran|retira|quita|coloca)\b.*\bpilonas?\b",
    r"\b(se )?(abren|cierran|abre|cierra)\b.*\b" + _OPENABLE + r"\b",
    r"\b(se )?(conectan|desconectan|conecta|desconecta|encienden|enciende|"
    r"apagan|apaga)\b.*\b(rampa|rampas|alumbrado|luces|luz|ascensor|escalera|"
    r"monitores|fachada|sistemas de seguridad)\b",
    r"\b(se )?(realizan?|hacen?|efectuan?)\b.*\b(rondas?|revisiones?|control)\b",
    r"\b(se )?(revisan?|revisa)\b.*\b(zonas?|alumbrado|cierres?|centro|aseos?|"
    + _ZONE + r")\b",
    r"^revision\b",
    r"\bronda\b.*\bsin (novedad|incidencias)\b",
    # "sin novedad" anywhere: nothing happened, wherever the phrase sits.
    r"\bsin (novedad|novedades|incidencia|incidencias)\b",
    r"\bno hay (novedad\w*|incidencia\w*)\b",
    r"^nuevo turno\b",
    r"\b(salida|entrada)\b.*\b(empleados|personal)\b",
    # Written as a noun phrase with no verb: "Apertura muelle", "Alumbrado tarde".
    r"^(apertura|cierre)\b.*\b" + _OPENABLE + r"\b",
    r"^alumbrado\b",
    # Written as a noun phrase: "Cierre de pilonas", "Conexion del alumbrado",
    # "Incorporacion del vigilante de noche", "Entrada de servicio".
    r"^(apertura|cierre|colocacion|retirada)\b.*\bpilonas?\b",
    r"^(conexion|desconexion|encendido|apagado)\b.*"
    r"\b(alumbrado|luces|luz|ascensor|rampa|rampas|sistemas)\b",
    r"^(incorporacion|salida|entrada|relevo)\b.*"
    r"\b(vigilante|vigilantes|personal|empleados?|servicio|turno)\b",
    r"^(rondas?|revision|revisiones)\b",
    r"\b(se )?(cierran|cierra|retiran|retira)\b.*"
    r"\b(pilonas?|pinonas?|accesos?)\b",
    r"\b(se )?(comienza|empieza)\b.*\bcerrar\b",
    r"\bcierre parcial\b",
    r"\bcontrol de acceso\b",
    # The guard arriving or leaving is a shift operation, in the verb form as
    # well as the noun one already above.
    r"\b(se )?(incorpora|incorporan|releva|relevan)\b.*"
    r"\b(vigilante|vigilantes|servicio|turno|puesto)\b",
)

# Shift routine that never belongs in the memoria, named by the author:
# switching the evening and night lighting, starting and finishing the
# closing round, and putting out or taking in the bollards. Kept apart from
# _ROUTINE because tools/omit_shift_routine.py applies exactly these to lines
# already stored.
#
# Stems, not forms, and the usual misreadings: September's came through as
# "Conector [?] alumbrado tarde" (conecta/conexion misread), "Comienzo el
# cierre", "Finalizo cierre" and "Se colocan pelonas" -- and a list of exact
# words let every one of them into the document.
_PILONAS = r"(pilon|pinon|pelon|pelicul)\w*"
_SHIFT_ROUTINE = (
    r"\balumbrado\b.*\b(tarde|noche|nocturno|exterior|fachada)\b",
    r"\b(tarde|noche|nocturno|exterior)\b.*\balumbrado\b",
    r"\b(conect|conex|desconect|desconex|encend|enciend|apag)\w*\b.*\balumbrado\b",
    r"\balumbrado\b.*\b(conect|conex|desconect|desconex|encend|enciend|apag)\w*\b",
    r"\b(comienz|empiez|inici)\w*\b.*\bcierre\b",
    r"\b(finaliz|termin|acab)\w*\b.*\bcierre\b",
    # The bollards as what is put out or taken in, a word or so after the
    # verb -- not "colocando pegatinas refractarias en pilonas", which the
    # author kept.
    r"\b(coloc|pon|retir|quit)\w*\s+(\w+\s+)?" + _PILONAS + r"\b",
    r"^(colocacion|retirada)\b.*\b" + _PILONAS + r"\b",
    # Opening, closing or checking the torreones, whichever comes first --
    # "se revisan torreones y se abren" put the noun before the verb and
    # slipped past the verb-first rule. "Torretas" is how the model misreads
    # them. Naming who one was opened for stays an event, as always.
    r"\b(abr|cierr|cerr|revis)\w*\b.*\b(torreon|torreones|torretas?)\b",
    r"\b(torreon|torreones|torretas?)\b.*\b(abr|cierr|cerr|revis)\w*\b",
    r"^(apertura|cierre|revision)\b.*\b(torreon|torreones|torretas?)\b",
    # Customers and staff leaving the Poker, the salon open latest, is how the
    # night shift ends: "Salida clientes Poker", "Salida empleada Poker".
    # "Posier" is how the reader gets the name. Anything that happened on the
    # way out -- a call, an expulsion, a complaint -- is an event as ever.
    r"^(salida|salen|sale|entrada|entran|entra)\b\s+(de\s+)?(los\s+|las\s+|la\s+|el\s+)?"
    r"(clientes?|emplead\w*|personal|encargad\w*)\b.*\b(poker|posier)\b",
    # The guard coming on: "Se incorpora V.S", "Incorporacion del VS noche",
    # "Se incorpora el vigilante de noche", or the bare "Vigilante de noche".
    # Other people joining the service are not this: "Se incorporan al
    # servicio dos companeros en practicas" stays.
    r"\bincorpor\w*\b.*(\bv\.?\s?s\b|\bvigilante\w*)",
    r"(\bv\.?\s?s\b|\bvigilante\w*).*\bincorpor\w*",
    r"^(el\s+)?(v\.?\s?s\.?|vigilante)\s+(de\s+)?(noche|nocturno|tarde|manana|dia)\W*$",
    # The signs put out every day on the stairs and the 3-6 corridor:
    # "Se colocan carteles en escaleras y pasillo 3-6". The sign has to sit on
    # the stairs or the corridor itself -- "carteles de prohibido el paso en
    # la escalera" names a closure and stays, as does a sign on a machine.
    r"\b(coloc|pon)\w*\s+cartel(es)?\s+(en|de)\s+(las?\s+|el\s+)?"
    r"(escaleras?|pasillo|pasarela)\b",
    # And the exit sign at zona 4: "Se coloca cartel de salida en zona 4
    # planta 1", "Se coloca el cartel zona 4". "7-4" is how the model reads
    # "Z-4". A sign on the zona 4 lifts, or one with a reason, stays.
    r"\b(coloc|pon)\w*\s+(el\s+)?cartel\s+de\s+salida\b",
    r"\b(coloc|pon)\w*\s+(el\s+)?cartel\s+((en|de)\s+)?(la\s+)?"
    r"(zona\s*4|z\s?-?\s?4|7\s?-\s?4)\b",
)

# ...but only when the line says nothing more. Measured against the 5854
# entries of the 38 hand-revised memorias, the bare patterns would have
# hidden 17 the author kept, and every one carried something extra: a
# purpose ("para la carga del catering", "por gases toxicos"), a cause ("por
# lluvia", "debido a la poca claridad"), what was left behind ("quedando
# una furgoneta"), or something out of the ordinary ("alumbrado de navidad",
# "reparando", "ausencia luz", "se requiere a mantenimiento").
_SHIFT_EXTRA = (
    r"\b(para|por|debido|porque|ya que|quedando|queda|quedan|dentro|hay|"
    r"parcial\w*|navidad|requier\w*|ausencia|repar\w*|llega\w*|activa\w*|"
    # People: a closing after "los trabajadores de Yoigo" leave is kept.
    r"trabajador\w*|tecnic\w*|operari\w*|se van|se marcha\w*)\b"
)

# If any of these appear the line is an event, whatever else it says.
# A verb that needs an object or a complement, left with neither: "Se
# procede." says nothing, and the words that followed it were lost.
_DANGLING = re.compile(
    r"(se\s+)?(procede|realiza|efectua|continua|prosigue|observa|comprueba"
    r"|revisa|verifica)n?"
)

_NOTABLE = (
    # A stretch nobody could read is never hidden: someone has to read it.
    r"\bgrupo de texto ilegible\b",
    r"\bllama\w*\s+la\s+atencion\b", r"\bexpuls\w+", r"\bqueja\b", r"\bavis\w+",
    r"\baveri\w+", r"\bdesperfecto\w*", r"\brobo\b", r"\bhurto\b",
    r"\bincidente\w*", r"\balarma\b", r"\bfuga\b", r"\bpelea\b", r"\bforzad\w+",
    r"\bindigente\b", r"\bembriaguez\b", r"\bpolicia\b", r"\b091\b", r"\b112\b",
    # Plural as well as singular: the vigilantes write "se observan luces" as
    # readily as "se observa", and matching only the singular hid the line.
    r"\bse observan?\b", r"\bse detectan?\b", r"\bse impiden?\b",
    r"\bse asisten?\b", r"\bse comunican?\b", r"\bse contactan?\b",
    r"\bse reciben?\b",
    # Stems, not exact forms. The author writes "averiado" as often as
    # "averia", "informando" as often as "se informa", "llamada" as often as
    # "llamo"; matching only one form hid the other.
    r"\binform\w+", r"\bcomunicad\w+", r"\bllamad\w+",
    r"\bencontr\w+", r"\bencuentr\w+", r"\bhallad\w+",
    r"\bmal (uso|comportamiento)\b", r"\bno autorizad\w+", r"\bsin autorizacion\b",
    # Verbs the vigilantes use when something actually happened. Taken from the
    # incident list of the hand-written memoria.
    r"\b(se |me )?acude\b", r"\b(se )?persona\b.*\b(para|por)\b",
    r"\b(se )?controla\b", r"\b(se )?presenta\b", r"\b(se )?asiste\b",
    r"\b(se )?detiene\b", r"\b(se )?desmonta\b", r"\b(se )?entrega\b",
    r"\b(se )?facilita\b", r"\b(se )?deposita\b", r"\b(se )?balizan?\b",
    r"\b(se )?recuerda\b", r"\b(se )?explica\b", r"\b(se )?indica\b",
    r"\b(se )?levanta\b", r"\bguardan? imagenes\b", r"\bmira\b.*\bcamara\b",
    r"\brecibo una llamada\b", r"\bllamo\b", r"\b(se )?ve a\b",
    r"\bdando voces\b", r"\bsalto de alarma\b",
    # Something happened, even if it did no damage: "Se produce un seismo sin
    # novedad" is an event, where "Se produce un cierre sin novedad" is not.
    # The noun decides, not the verb -- a cierre is shift operation, a seismo
    # is an occurrence.
    r"\bseismo\b", r"\bterremoto\b", r"\bincendio\b", r"\bsalto\b",
    r"\bsalta\b.*\balarma\b", r"\binundacion\b", r"\bapagon\b",
    # Opening or closing FOR a reason is an event: "Se abre el muelle para
    # retirar la compactadora". The routine version names no purpose.
    r"\b(abre|abren|cierra|cierran|conecta|conectan)\b.*\b(para|por|al)\b",
    # An opening that names who it was for is an event, in the noun form as
    # well as the verb: "Apertura a tecnico de Aguasur", "Apertura de Z-4 P0
    # para los repartidores de hielo". A bare one names only a place and stays
    # routine -- "Apertura muelle", "Apertura accesos gimnasio".
    r"\bapertura\b.*\b(a|al|para)\b",
    # An authorisation names who granted it, and appeared in 78 approved
    # entries and no routine one.
    r"\bautorizad\w+",
    # Naming the person a door was opened for is what separates the entries
    # the author kept from the ones he left out, whichever verb carries it:
    # "Se abre el torreon de zona 4 a un tecnico de telefonia" against the
    # bare "Se abre Z6-1".
    r"\b(a|al|para)\s+(los\s+|las\s+|un\s+|una\s+|el\s+|la\s+)?"
    r"(tecnic\w+|operari\w+|repartidor\w+|transportista\w*|proveedor\w+|"
    r"personal\b|empresa\b|bombero\w*|polic\w+|client\w+)",
    # Something broken is an event even when the sentence around it is a
    # routine check: "estando la mayoria de los pestillos rotos".
    r"\brot[oa]s?\b",
    # Lighting that fails is an incident, never the routine switching above.
    r"\bno (funciona\w*|enciende\w*|encienden|se enciende\w*|conecta\w*|va)\b",
    r"\bfall(a|an|o|os)\b", r"\bfundid\w*", r"\bse funden?\b",
    r"\bcortes? de (luz|corriente)\b", r"\bsin (luz|corriente)\b",
)


# Fewer real letters than this and the line carries no information: the reader
# got a time and a smudge. Real entries are whole sentences.
MIN_LETTERS = 8


def is_noise(text: str) -> bool:
    """True when nothing legible survived: "22:10 -", "S.A. ...", "".

    These come from lines where the reader caught the clock but not the words.
    They are dropped rather than written into the document as empty bullets.
    """
    stripped = strip_time_prefix(text)
    return sum(c.isalpha() for c in stripped) < MIN_LETTERS


def reads_as_event(text: str) -> bool:
    """True when the line describes something that happened.

    Checked independently of who called the line routine, because hiding an
    incident is the one failure that matters in this document.
    """
    folded = _fold(strip_time_prefix(text))
    return any(re.search(p, folded) for p in _NOTABLE)


def is_shift_routine(text: str) -> bool:
    """True for bare lighting, closing-round and bollard routine."""
    folded = _fold(strip_time_prefix(text))
    if not folded or reads_as_event(text) or re.search(_SHIFT_EXTRA, folded):
        return False
    return any(re.search(p, folded) for p in _SHIFT_ROUTINE)


def is_routine_text(text: str) -> bool:
    """True when the line is plainly ordinary shift operation."""
    folded = _fold(strip_time_prefix(text))
    if not folded or reads_as_event(text):
        return False
    return any(re.search(p, folded) for p in _ROUTINE) or is_shift_routine(text)
