"""The HTTP server: which address may ask, what a POST must carry, and how a
sheet reference turns into bytes on disk.

There is no login (see dashboard_auth). The only gate is the network a
request arrives from, checked once in handle() before ROUTES is even
consulted -- a route registered next year is covered by that check simply by
existing in the dict, not by whoever writes it remembering to call
is_allowed() themselves. Every state-changing route additionally requires a
CSRF token -- and *that* guard is also carried by the route table, as a flag
on the Route rather than a branch on the HTTP verb, so the same "a route
covers itself" property holds for it too.

Routing is deliberately not framework-shaped: handle() is a pure function of
(method, path, address, host, form, store) so the whole route table can be
tested by calling it directly, without a socket.
"""

import argparse
import html
import logging
import mimetypes
import os
import re
import sqlite3
import threading
import time
import weakref
from collections import Counter, OrderedDict
from collections.abc import Callable
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import NamedTuple
from urllib.parse import parse_qs, quote, unquote, urlsplit

from config import config
from dashboard_auth import is_allowed, is_allowed_host, new_token, sees_advanced, token_matches
from dashboard_html import (SECTION_PATHS, editor, maintenance_page, page, save_control,
                            summary, with_maintenance_strip)
from entry_store import (MANTENIMIENTO_SECTION, SEGURIDAD_SECTION, EntryStore,
                         section_of_block)
from main import rebuild_memoria
from memoria import SEGURIDAD_BLOCK
from memoria_blocks import SHORT_NAMES, block_from_slug, slug_of
from month_folders import MONTH_FOLDERS, memoria_name, processed_dir_for, revision_dir_for
import nettune_feedback
from page_rotation import rotate_by
from review_marks import image_name, plain_ref
from sheet_dates import set_sheet_date
from spend_guard import SpendGuard


class Response(NamedTuple):
    status: int
    body: bytes
    content_type: str
    headers: dict[str, str]


def _text(status: int, message: str) -> Response:
    return Response(status, message.encode("utf-8"), "text/plain; charset=utf-8", {})


def _html(status: int, body: str) -> Response:
    # no-store so the back button asks again instead of showing a page from
    # memory: after a turn or an edit, going back must show what is saved,
    # not what was on screen before it.
    return Response(status, body.encode("utf-8"), "text/html; charset=utf-8",
                    {"Cache-Control": "no-store"})


def _redirect(location: str) -> Response:
    return Response(303, b"", "text/plain", {"Location": location})


# --- CSRF tokens ------------------------------------------------------------
# One token per address, held in memory. There is no session to hang it from
# -- no login means no cookie a session could ride on -- so the same address
# that was handed a token on a GET is the one asked to produce it again on
# the POST that follows.
#
# 127.0.0.0/8 is in dashboard_auth.ALLOWED_NETWORKS (the Pi talking to
# itself), which means any local process can ask for a token; nothing here
# stops that, but a token on its own unlocks nothing without also being on
# an allowed network, and an unbounded dict fed from loopback would still be
# a leak. So: a lifetime after which a token stops working, and a cap on how
# many addresses are remembered at once, oldest first.
_MAX_TOKENS = 64
_TOKEN_TTL_SECONDS = 8 * 60 * 60  # a working day; no login means no sign-out
_tokens: OrderedDict[str, tuple[str, float]] = OrderedDict()


def _token_for(address: str) -> str:
    now = time.monotonic()
    cached = _tokens.get(address)
    if cached and cached[1] > now:
        _tokens.move_to_end(address)
        return cached[0]
    token = new_token()
    _tokens[address] = (token, now + _TOKEN_TTL_SECONDS)
    _tokens.move_to_end(address)
    while len(_tokens) > _MAX_TOKENS:
        _tokens.popitem(last=False)
    return token


def _check_csrf(address: str, form: dict) -> bool:
    cached = _tokens.get(address)
    if not cached:
        return False
    token, expires_at = cached
    if expires_at <= time.monotonic():
        del _tokens[address]
        return False
    return token_matches(token, form.get("csrf"))


# --- One connection per thread, not one connection shared by all -----------
# EntryStore opens its sqlite connection with the default check_same_thread
# =True, and that has to stay true: the ingestion pipeline is single-threaded
# by design and shares the class. Each request runs in a thread of its own
# (see make_server), so _resolve_store gives every thread but the one that
# built *store* a connection of its own to the same file: it tries *store*
# directly first, and only opens another connection when that fails.
# make_server touches *store* once from the owning thread first, which is
# what lets _resolve_store learn the file's path.
_known_db_paths: "weakref.WeakKeyDictionary[EntryStore, str]" = weakref.WeakKeyDictionary()
_thread_local = threading.local()
_dispatch_lock = threading.Lock()


def _thread_store(path: str) -> EntryStore:
    """This thread's own EntryStore over *path*, opened once and reused.

    More than one connection to the same file is safe under WAL mode, which
    EntryStore already turns on; a write through one is visible to a read
    through another as soon as it commits.
    """
    cache = getattr(_thread_local, "stores", None)
    if cache is None:
        cache = {}
        _thread_local.stores = cache
    thread_store = cache.get(path)
    if thread_store is None:
        thread_store = EntryStore(path, recorder=nettune_feedback.recorder())
        cache[path] = thread_store
    return thread_store


def _resolve_store(store: EntryStore) -> EntryStore:
    """*store* itself, if this thread is the one that may use it; otherwise
    a stand-in connection to the same file (see _thread_store).

    The path is cached the moment a direct access succeeds, from wherever
    that happens to be -- normally the very first request -- so a later
    request from a thread that owns nothing can still be served instead of
    raising. Nothing before that point can be recovered: without ever having
    touched *store* safely, there is no way to learn what file it opened.
    """
    try:
        store._connection.execute("SELECT 1")
    except sqlite3.ProgrammingError:
        path = _known_db_paths.get(store)
        if path is None:
            raise
        return _thread_store(path)
    _known_db_paths[store] = store._connection.execute(
        "PRAGMA database_list"
    ).fetchone()[2]
    return store


def _find_entry(store: EntryStore, entry_id: int) -> dict | None:
    """Which month holds this id, without trusting anything but the id itself.

    EntryStore addresses an entry's text by rowid alone, but placing it back
    on the page, or deriving where a new sibling line belongs (see
    _handle_entrada_nueva), needs the month it lives in too. The table is one
    centre's worth of months, so scanning all of them costs nothing next to
    the OpenAI calls the rest of the app makes.
    """
    location = store.entry_month(entry_id)
    if location is None:
        return None
    year, month = location
    for entry in store.month_entries(year, month):
        if entry["id"] == entry_id:
            found = dict(entry)
            found["year"] = year
            found["month"] = month
            return found
    return None


def _sheet_count(store: EntryStore, year: str, month: str) -> int:
    """How many distinct sheets have ever carried a review marker this month,
    confirmed or not -- see _handle_hoja for why "confirmed" does not mean
    "gone".
    """
    return len({
        entry["review_ref"] for entry in store.month_entries(year, month)
        if entry.get("review_ref")
    })


def _spend_eur() -> str | None:
    """This month's real OpenAI spend in euros, or None if it cannot be read.

    A fabricated number is worse than a missing one: the advanced view is
    read by the one person who would act on it being wrong.
    """
    try:
        with SpendGuard(
            config.spend_db,
            monthly_budget_eur=config.monthly_budget_eur,
            eur_usd=config.eur_usd,
        ) as guard:
            return f"{guard.spent_this_month() / config.eur_usd:.2f}"
    except Exception as exc:
        logging.error(f"No se pudo leer el gasto del mes: {exc}")
        return None


def _stats(store: EntryStore, year: str, month: str) -> dict:
    """What the command bar shows: the colleague's counts, and (if summary()
    is told to) the author's numbers beside them.

    Every number here is sourced from something real; there used to be a
    "días" figure with nothing behind it and a "hojas" that was actually the
    annotation total under a sheet-count label -- both gone or fixed, per the
    rule that a wrong label is worse than a missing one.
    """
    # Doubtful sheets and empty ones: both need a person to look.
    sheets = store.to_check(year, month)
    counts = store.counts(year, month)
    total = sum(counts.values())
    flagged = store.flagged_count(year, month)
    hand_edited = store.hand_edited_count(year, month)
    revisado = 100 if total == 0 else round((total - flagged) / total * 100)
    gasto = _spend_eur()
    return {
        "pendientes": len(sheets),
        "anotaciones": total,
        "documento": _document_state(store, year, month, len(sheets)),
        "revisado": revisado,
        "sistema": bool(config.openai_api_key),
        "gasto": gasto if gasto is not None else "sin datos",
        "tope": f"{config.monthly_budget_eur:.2f}",
        "modelo": config.model_name,
        "hojas": _sheet_count(store, year, month),
        "marcadas": flagged,
        "corregidas": hand_edited,
    }


def _document_state(store: EntryStore, year: str, month: str, pending: int) -> str:
    """One line on where the month's final document stands."""
    if not store.all_pages(year, month):
        return ""
    folder = processed_dir_for(config.incoming_dir, year, month)
    if pending:
        hojas = "1 hoja" if pending == 1 else f"{pending} hojas"
        written = _written_at(os.path.join(folder, memoria_name(year, month, draft=True)))
        if written is None:
            return f"Documento final: falta revisar {hojas}"
        return (f"Borrador guardado el {written:%d/%m a las %H:%M}; "
                f"para el documento final falta revisar {hojas}")
    written = _written_at(os.path.join(folder, memoria_name(year, month)))
    if written is None:
        return "Todo revisado: pulse Guardar para generar el documento final"
    return f"Documento final generado el {written:%d/%m a las %H:%M}"


def _written_at(path: str) -> datetime | None:
    try:
        return datetime.fromtimestamp(os.path.getmtime(path), tz=timezone.utc).astimezone()
    except OSError:
        return None


def _current_year_month() -> tuple[str, str]:
    now = datetime.now()
    return str(now.year), MONTH_FOLDERS[now.month - 1]


# --- Route handlers -------------------------------------------------------
# Each takes (method, params, form, store, address) and returns a Response.
# handle() has already refused an outside address and a bad Host header, and
# a mutating route without a valid CSRF token, by the time one of these runs.


def _selected_sheet(store: EntryStore, year: str, month: str, reference: str | None) -> str | None:
    """*reference* if it names a sheet one of this month's entries actually
    points at, else None.

    The same rule /hoja/{reference} enforces on the file it serves: a value
    from the query string is only ever compared against review_ref values
    the database holds, by way of image_name -- never joined to a path. A
    query string carrying "../../etc/passwd" simply matches nothing here,
    so the image pane falls back to "no sheet selected" rather than ever
    seeing that text again.
    """
    if not reference:
        return None
    # Every sheet of the month, not only those a line points at: a sheet
    # recorded by the scan alone -- the pages rebuilt from the archive --
    # must open too, or it can be offered as a candidate but never looked at.
    for ref in store.all_pages(year, month):
        if image_name(ref) == reference:
            return reference
    return None


def _is_month(year: str, month: str) -> bool:
    """A year and a month folder name, and nothing else: they become paths."""
    return len(year) == 4 and year.isdigit() and month in MONTH_FOLDERS


def _handle_mes(method, params, form, store, address, section: str = "seguridad"):
    """A month in one section: Seguridad's block and sheets, or Mantenimiento's.

    Both kinds of sheet are filed into the same month and the same memoria;
    each tab shows only its own, so the maintenance crew's sheets no longer
    turn up among the vigilantes'. A sheet belongs where its scan's lines
    went (EntryStore.sheet_sections) -- one maintenance sheet with a single
    line under Parking is still a maintenance sheet.
    """
    if method != "GET":
        return _text(405, "Método no permitido")
    year, month = params["year"], params["month"]
    if not _is_month(year, month):
        return _text(404, "No existe ese mes")
    token = _token_for(address)
    sheet_blocks = store.sheet_blocks(year, month, SEGURIDAD_BLOCK)
    sections = store.sheet_sections(year, month)

    def mine(ref: str) -> bool:
        return sections.get(ref, SEGURIDAD_SECTION) == section

    entries = [e for e in store.month_entries(year, month)
               if section_of_block(e.get("block", "")) == section]
    # Mantenimiento: how many lines each subheading has this month, and the
    # one being shown, if any. The counts are taken before filtering, so the
    # bar always describes the whole month.
    tag_counts = None
    tag_filter = ""
    moved_to = ""
    if section == MANTENIMIENTO_SECTION:
        moved_to = slug_of(block_from_slug(params.get("movida")))
        tag_counts = Counter(e["block"] for e in entries)
        filtro = block_from_slug(params.get("bloque"))
        if filtro:
            tag_filter = slug_of(filtro)
            entries = [e for e in entries if e["block"] == filtro]
    # "Por revisar": sheets with a doubtful line, and sheets with no lines.
    sheets = {ref: n for ref, n in store.to_check(year, month).items() if mine(ref)}
    # Every sheet of the batch, for the person who would rather read the whole
    # month against the paper than trust the flags to have caught everything.
    all_sheets = {ref: n for ref, n in store.all_pages(year, month).items() if mine(ref)}
    # Every sheet by default; the shortlist only when asked for.
    showing_all = params.get("hojas") != "pendientes"
    selected = _selected_sheet(store, year, month, params.get("hoja"))
    advanced = sees_advanced(address)
    candidates = {
        e["id"]: store.candidate_sheets(e["id"])
        for e in entries if not e.get("review_ref")
    }
    date_checks = store.date_checks(year, month)
    body = editor(
        year, month, entries, token, sheets, selected_hoja=selected,
        all_sheets=all_sheets, showing_all=showing_all, months=store.months(),
        candidates=candidates, date_checks=date_checks, sheet_blocks=sheet_blocks,
        section=section, tag_counts=tag_counts, tag_filter=tag_filter,
        moved_to=moved_to,
    )
    titulo = "Memoria" if section == "seguridad" else "Mantenimiento"
    return _html(200, page(
        f"{titulo} {month} {year}", body, advanced=advanced, active=section,
        year_month=(year, month),
        resumen=summary(_stats(store, year, month), advanced),
        acciones=save_control(year, month, token, selected_hoja=selected,
                              showing_all=showing_all, section=section,
                              tag_filter=tag_filter),
    ))


def _handle_mes_mantenimiento(method, params, form, store, address):
    return _handle_mes(method, params, form, store, address, section="mantenimiento")


_PENDIENTE = re.compile(r"^texto-(\d+)$")


def _apply_pending_edits(store: EntryStore, form: dict, year: str, month: str) -> int:
    """Save the lines typed into but not yet saved. Returns how many were refused.

    Each line is its own form, so a browser only ever submits the one that
    was pressed. Editing three boxes and then pressing Guardar línea on one
    of them -- or Guardar, or Correcto, or a rotate button -- used to throw
    the other two away on the reload that followed. The page's script now
    rides every edited box along with whichever form is submitted, as
    texto-{id}, and every writing route applies them first.

    Scoped to the month the request is about: an id from another month, or
    one that no longer exists, is ignored rather than trusted. A box whose
    text is unchanged is skipped, so a submit does not mark every line on
    the page as corrected by hand. A refusal is edit_entry's own -- an empty
    box, or text that duplicates another line in the block.
    """
    actuales = {e["id"]: e["text"] for e in store.month_entries(year, month)}
    rechazadas = 0
    for clave, valor in form.items():
        coincide = _PENDIENTE.match(clave)
        if not coincide:
            continue
        entry_id = int(coincide.group(1))
        if entry_id not in actuales:
            continue
        if (valor or "").strip() == (actuales[entry_id] or "").strip():
            continue
        if not store.edit_entry(entry_id, valor):
            rechazadas += 1
    return rechazadas


def _back_to_month(
    store: EntryStore, year: str, month: str, form: dict, entry_id: int | None = None,
    moved: str = "",
) -> Response:
    """Redirect to the month page as the person left it.

    Every write used to redirect to the bare month URL, so pressing Guardar
    línea with a sheet open closed the sheet and scrolled back to the top.
    The forms now carry the view -- which sheet is open, which list is
    showing -- as hidden fields, and this puts them back.

    Nothing from the form is echoed unchecked: hoja goes through the same
    database lookup as the query string does (_selected_sheet), hojas is
    only ever the literal "todas", and bloque is only ever one of the four
    slugs. entry_id comes from the route, not the
    form, and lands the page back on the line that was just touched.
    """
    query = []
    hoja = _selected_sheet(store, year, month, form.get("hoja"))
    if hoja:
        query.append(f"hoja={quote(hoja)}")
    # "todas" is the default and needs no parameter; only the shortlist does.
    if form.get("hojas") == "pendientes":
        query.append("hojas=pendientes")
    # The tag being shown on the Mantenimiento page; only a known slug.
    filtro = slug_of(block_from_slug(form.get("bloque")))
    if filtro:
        query.append(f"bloque={filtro}")
    # A line just moved out of the tag being shown: the page says where to.
    movida = slug_of(block_from_slug(moved))
    if movida:
        query.append(f"movida={movida}")
    # Back to the section the form was posted from; only the known names.
    base = SECTION_PATHS.get(form.get("seccion", ""), SECTION_PATHS["seguridad"])
    location = f"{base}/{year}/{month}"
    if query:
        location += "?" + "&".join(query)
    if entry_id is not None:
        location += f"#entrada-{entry_id}"
    return _redirect(location)


def _handle_entrada(method, params, form, store, address):
    """Inline correction of one line's text."""
    if method != "POST":
        return _text(405, "Método no permitido")
    try:
        entry_id = int(params["id"])
    except ValueError:
        return _text(404, "No encontrado")
    located = _find_entry(store, entry_id)
    if located:
        _apply_pending_edits(store, form, located["year"], located["month"])
    if not store.edit_entry(entry_id, form.get("texto", "")):
        return _text(400, "No se pudo guardar la corrección")
    if located:
        return _back_to_month(store, located["year"], located["month"], form, entry_id)
    return _text(200, "Guardado")


def _handle_asignar_hoja(method, params, form, store, address):
    """File a line with no recorded sheet under the one a person picked.

    The form names an image; it is matched against the line's own
    candidates (EntryStore.candidate_sheets), never used as a reference in
    its own right, so nothing outside that short list can be chosen.
    """
    if method != "POST":
        return _text(405, "Método no permitido")
    try:
        entry_id = int(params["id"])
    except ValueError:
        return _text(404, "No encontrado")
    located = _find_entry(store, entry_id)
    if located is None:
        return _text(404, "No encontrado")
    year, month = located["year"], located["month"]
    _apply_pending_edits(store, form, year, month)
    elegida = form.get("hoja_elegida", "")
    ref = next((c for c in store.candidate_sheets(entry_id)
                if image_name(c) == elegida), None)
    if ref is None or not store.assign_sheet(entry_id, ref):
        return _text(400, "Esa hoja no es una de las posibles para esta línea")
    # The view stays as it was -- whichever sheet was open stays open. It
    # used to switch to the chosen sheet, which forced a whole-page load
    # and pulled the person away from the sheet they were reading.
    return _back_to_month(store, year, month, form, entry_id)


def _handle_entradas(method, params, form, store, address):
    """The confirm/revisar/eliminar buttons: a whole-row action, not a text edit."""
    if method != "POST":
        return _text(405, "Método no permitido")
    try:
        entry_id = int(params["id"])
    except ValueError:
        return _text(404, "No encontrado")
    # Looked up before acting: once remove_entry runs, the row -- and the
    # month it would redirect back to -- is gone.
    located = _find_entry(store, entry_id)
    if located:
        _apply_pending_edits(store, form, located["year"], located["month"])
    accion = form.get("accion")
    if accion == "confirmar":
        store.confirm_entry(entry_id)
    elif accion == "revisar":
        store.flag_entry(entry_id)
    elif accion == "eliminar":
        store.remove_entry(entry_id)
    else:
        return _text(400, "Acción desconocida")
    if located:
        # A removed line has no row left to scroll back to.
        volver_a = entry_id if accion in ("confirmar", "revisar") else None
        return _back_to_month(store, located["year"], located["month"], form, volver_a)
    return _text(200, "Guardado")


def _handle_entrada_nueva(method, params, form, store, address):
    """A line the reader missed, added by hand.

    year, month and block are read from the after_id row, never from the
    form: add_entry() positions the new line relative to after_id without
    checking they share a block, so trusting the submitted block would let a
    request name an after_id from one block and a block from another,
    computing a position against rows it has nothing to do with. Deriving
    all three from the anchor row removes that mismatch at its only caller.
    """
    if method != "POST":
        return _text(405, "Método no permitido")
    # Exactly one of after_id / before_id: "add below this line" from a row,
    # "add above the first line" from a sheet heading.
    after_raw, before_raw = form.get("after_id", ""), form.get("before_id", "")
    if bool(after_raw) == bool(before_raw):
        return _text(400, "Falta la línea de referencia")
    try:
        anchor_id = int(after_raw or before_raw)
    except ValueError:
        return _text(400, "Falta la línea de referencia")
    anchor = _find_entry(store, anchor_id)
    if anchor is None:
        return _text(404, "No encontrado")
    year, month, block = anchor["year"], anchor["month"], anchor["block"]
    _apply_pending_edits(store, form, year, month)
    texto = form.get("texto", "")
    nuevo = store.add_entry(
        year, month, block, texto,
        after_id=anchor_id if after_raw else None,
        before_id=anchor_id if before_raw else None,
    )
    if not nuevo and texto.strip():
        volver = _back_to_month(store, year, month, form, anchor_id).headers["Location"]
        body = (
            "<p>No se pudo añadir la línea: ya existe una igual en el mismo "
            "apartado.</p>"
            f'<p><a href="{html.escape(volver)}">Volver al documento</a></p>'
        )
        return _html(200, page("Aviso", body, advanced=sees_advanced(address)))
    return _back_to_month(store, year, month, form, nuevo or anchor_id)


def _handle_guardar(method, params, form, store, address):
    if method != "POST":
        return _text(405, "Método no permitido")
    year, month = params["year"], params["month"]
    if not _is_month(year, month):
        return _text(404, "No existe ese mes")
    rechazadas = _apply_pending_edits(store, form, year, month)
    # Every Guardar writes the document. Until every sheet has been checked
    # it is the draft, named so; the status line says how many are left.
    # Writing nothing until then looked, from the share, like Guardar had
    # failed -- the only .docx there was an old one.
    try:
        rebuild_memoria(store, year, month, draft=bool(store.to_check(year, month)))
    except Exception as exc:
        # Any failure downstream of the database write must not look like
        # the correction was lost -- it wasn't; only the document is stale.
        logging.error(f"No se pudo generar la memoria de {month} {year}: {exc}")
        body = "<p>Los cambios se han guardado, pero el documento no se pudo generar.</p>"
        return _html(200, page("Aviso", body, advanced=sees_advanced(address)))
    if rechazadas:
        # Saying nothing would look exactly like success, and the refused
        # boxes would quietly go back to their old text on the reload.
        volver = _back_to_month(store, year, month, form).headers["Location"]
        if rechazadas == 1:
            detalle = ("1 línea no se pudo guardar: estaba vacía o repetía el "
                       "texto de otra línea del mismo apartado.")
        else:
            detalle = (f"{rechazadas} líneas no se pudieron guardar: estaban "
                       "vacías o repetían el texto de otra línea del mismo apartado.")
        body = (
            f"<p>El documento se ha guardado, pero {detalle}</p>"
            f'<p><a href="{html.escape(volver)}">Volver al documento</a></p>'
        )
        return _html(200, page("Aviso", body, advanced=sees_advanced(address)))
    return _back_to_month(store, year, month, form)


def _locate_sheet(store: EntryStore, reference: str) -> tuple[str, str, str] | None:
    """(year, month, path) for the sheet *reference* names, or None.

    The one place a URL-supplied reference is resolved to a file, so the
    rule holds for every caller: the text in the URL never touches the
    filesystem. It is only ever compared against review_ref values the
    database already holds, by way of review_marks.image_name (the same
    function that named the file when it was copied into the revision
    folder). Only once a match is found does the -- freshly recomputed, not
    user-supplied -- filename get joined to revision_dir_for(). A reference
    that matches nothing, however it is spelled, resolves to None with
    nothing ever opened.

    The lookup runs over every entry regardless of flagged: review_pages()
    filters to flagged = 1, so a sheet whose last doubtful line the colleague
    has just confirmed would otherwise vanish the moment he looks at it,
    which is exactly when he is looking at it. review_ref survives
    confirmation (confirm_entry only clears the flag), so month_entries()
    still has it.
    """
    # Every year and month the data holds, in one query -- not a fixed list
    # of years, which would 404 every image filed outside it.
    for year, month, review_ref in store.sheets():
        if image_name(review_ref) != reference:
            continue
        filename = image_name(review_ref)
        file_path = os.path.join(
            revision_dir_for(config.incoming_dir, year, month), filename
        )
        if not os.path.isfile(file_path):
            return None
        return year, month, file_path
    return None


def _handle_hoja(method, params, form, store, address):
    """A sheet image, served from the file _locate_sheet resolves."""
    if method != "GET":
        return _text(405, "Método no permitido")
    located = _locate_sheet(store, params["reference"])
    if located is None:
        return _text(404, "No encontrado")
    _, _, file_path = located
    with open(file_path, "rb") as handle_:
        data = handle_.read()
    content_type = (
        mimetypes.guess_type(file_path)[0] or "application/octet-stream"
    )
    # no-store because the rotate buttons change this file underneath a
    # URL that never changes. Without it a person turns a sheet, the page
    # reloads, and the browser proudly shows them the cached sideways copy.
    return Response(200, data, content_type, {"Cache-Control": "no-store"})


def _handle_girar(method, params, form, store, address):
    """Turn one sheet a quarter at a time, at a person's request.

    The backstop for the sheets straighten() declines to touch. OSD reports
    a confidence for its reading and page_rotation refuses to act below
    MIN_CONFIDENCE, which is correct -- a wrong automatic rotation is worse
    than none -- but it leaves those sheets sideways with no way out but an
    SSH session. Someone looking at the sheet can see which way is up, so
    this takes the angle from them.

    It rewrites the file in the revision folder, which is what the colleague
    checks against, so the fix sticks for whoever opens it next rather than
    being one person's view of it. The scan it was split from is untouched,
    and so is the transcription: the text was read long before this, and
    turning the review copy does not make it stale.
    """
    if method != "POST":
        return _text(405, "Método no permitido")
    reference = params["reference"]
    located = _locate_sheet(store, reference)
    if located is None:
        return _text(404, "No encontrado")
    year, month, file_path = located
    _apply_pending_edits(store, form, year, month)
    try:
        degrees = int(form.get("grados", ""))
    except ValueError:
        return _text(400, "Giro no válido")
    try:
        rotate_by(file_path, degrees)
    except ValueError:
        return _text(400, "Giro no válido")
    except OSError as exc:
        logging.error(f"No se pudo girar {file_path}: {exc}")
        return _text(500, "No se pudo girar la hoja")
    # Recorded, not only applied: the file is not the only copy of this
    # decision any more, so whatever rewrites the file next can repeat it.
    store.record_turn(os.path.basename(file_path), degrees)
    # The sheet is known good here -- it was just located -- so it goes back
    # as it is; only the list choice comes from the form.
    return _back_to_month(store, year, month, {**form, "hoja": reference})


_ISO_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def _handle_fecha(method, params, form, store, address):
    """Settle a sheet's date: correct it, or confirm the one that was read.

    The date names the image and orders the month, and a misread one put
    September's page 3 among the 11ths. Only the paper says what it really
    is, so a person reads it and says so here; every line filed under the
    sheet moves with it, its file is renamed, and its hand turn follows.
    """
    if method != "POST":
        return _text(405, "Método no permitido")
    located = _locate_sheet(store, params["reference"])
    if located is None:
        return _text(404, "No encontrado")
    year, month, file_path = located
    old_name = os.path.basename(file_path)
    ref = next((r for r in store.all_pages(year, month) if image_name(r) == old_name), None)
    identity = store.sheet_identity(year, month, ref) if ref else None
    if identity is None:
        return _text(404, "No encontrado")
    _apply_pending_edits(store, form, year, month)

    fecha = (form.get("fecha") or "").strip()
    iso = _ISO_DATE.match(fecha)
    if iso:
        fecha = f"{iso.group(3)}-{iso.group(2)}-{iso.group(1)}"
    new_ref, error = set_sheet_date(
        store, year, month, ref, fecha, os.path.dirname(file_path),
        confirm_only=bool(form.get("confirmar")),
    )
    if new_ref is None:
        status = 500 if error.startswith("No se pudo renombrar") else 400
        return _text(status, error)
    new_name = image_name(new_ref)
    vista = dict(form)
    if vista.get("hoja") == old_name:
        vista["hoja"] = new_name
    return _back_to_month(store, year, month, vista)


def _handle_linea_en_hoja(method, params, form, store, address):
    """A line added to a sheet that has none yet.

    Every other way of adding a line places it beside an existing one; a
    sheet the reader found nothing on has none, so it could be opened but
    never filled in. The sheet comes from the URL and is looked up like any
    other (_locate_sheet); the block is the one its scan's lines went to.
    """
    if method != "POST":
        return _text(405, "Método no permitido")
    located = _locate_sheet(store, params["reference"])
    if located is None:
        return _text(404, "No encontrado")
    year, month, file_path = located
    name = os.path.basename(file_path)
    ref = next((r for r in store.all_pages(year, month) if image_name(r) == name), None)
    if ref is None:
        return _text(404, "No encontrado")
    _apply_pending_edits(store, form, year, month)
    block = store.sheet_blocks(year, month, SEGURIDAD_BLOCK).get(ref, SEGURIDAD_BLOCK)
    texto = form.get("texto", "")
    nuevo = store.add_to_sheet(year, month, block, ref, texto)
    if not nuevo:
        if not texto.strip():
            return _text(400, "Escriba la línea antes de añadirla")
        return _text(400, "Ya existe una línea igual en el mismo apartado")
    return _back_to_month(store, year, month, form, nuevo)


def _handle_hoja_vacia(method, params, form, store, address):
    """A person looked at an empty sheet and there is nothing to add."""
    if method != "POST":
        return _text(405, "Método no permitido")
    located = _locate_sheet(store, params["reference"])
    if located is None:
        return _text(404, "No encontrado")
    year, month, file_path = located
    name = os.path.basename(file_path)
    ref = next((r for r in store.all_pages(year, month) if image_name(r) == name), None)
    if ref is None:
        return _text(404, "No encontrado")
    _apply_pending_edits(store, form, year, month)
    store.confirm_empty(year, month, ref)
    return _back_to_month(store, year, month, form)


def _handle_resumen(method, params, form, store, address):
    if method != "GET":
        return _text(405, "Método no permitido")
    year, month = _current_year_month()
    advanced = sees_advanced(address)
    body = summary(_stats(store, year, month), advanced)
    return _html(200, page("Resumen", body, advanced=advanced))


def _most_recent_month_with_entries(store: EntryStore) -> tuple[str, str]:
    """The newest year/month that has anything in it, newest first.

    Falls back to the current calendar month when nothing has been read
    yet -- the bookmark has to land somewhere even on a brand new install.
    """
    months = store.months()
    if months:
        return months[-1]
    return _current_year_month()


def _handle_root(method, params, form, store, address):
    if method != "GET":
        return _text(405, "Método no permitido")
    year, month = _most_recent_month_with_entries(store)
    return _redirect(f"/mes/{year}/{month}")


def _handle_mantenimiento(method, params, form, store, address):
    if method != "GET":
        return _text(405, "Método no permitido")
    year, month = _most_recent_month_with_entries(store)
    return _redirect(f"{SECTION_PATHS['mantenimiento']}/{year}/{month}")


def _handle_etiqueta(method, params, form, store, address):
    """Move a maintenance line to another of the memoria's four subheadings.

    The new subheading comes from the form as a slug and is looked up, never
    used as given. A move onto an identical line already under that
    subheading is refused with an explanation, like a duplicate added line.
    """
    if method != "POST":
        return _text(405, "Método no permitido")
    try:
        entry_id = int(params["id"])
    except ValueError:
        return _text(404, "No encontrado")
    block = block_from_slug(form.get("etiqueta"))
    if not block:
        return _text(400, "Apartado desconocido")
    located = _find_entry(store, entry_id)
    if located is None:
        return _text(404, "No encontrado")
    if section_of_block(located["block"]) != MANTENIMIENTO_SECTION:
        return _text(400, "Solo las líneas de mantenimiento tienen apartado")
    year, month = located["year"], located["month"]
    _apply_pending_edits(store, form, year, month)
    # Moved out of the tag being shown, the line leaves the page: land on
    # the line that took its place in the list (the one before, if it was
    # the last), and say where it went.
    filtro = block_from_slug(form.get("bloque"))
    sale = bool(filtro) and located["block"] == filtro and block != filtro
    vecina = None
    if sale:
        visibles = [e["id"] for e in store.month_entries(year, month)
                    if e["block"] == filtro]
        i = visibles.index(entry_id)
        resto = visibles[i + 1:] + visibles[:i][::-1]
        vecina = resto[0] if resto else None
    result = store.retag_entry(entry_id, block)
    if result.status == "collision":
        volver = _back_to_month(store, year, month, form, entry_id).headers["Location"]
        otra = _find_entry(store, result.other_id) if result.other_id else None
        donde = ""
        if otra and otra.get("review_ref"):
            donde = f" (hoja {html.escape(plain_ref(otra['review_ref']))})"
        enlace_otra = ""
        if otra:
            # Shown under its own tag: with the old filter it would be hidden.
            ir = _back_to_month(store, year, month, {**form, "bloque": slug_of(block)},
                                result.other_id).headers["Location"]
            enlace_otra = f'<p><a href="{html.escape(ir)}">Ver la otra línea</a></p>'
        body = (
            "<p>No se pudo cambiar el apartado: ya hay una línea igual en "
            f"{html.escape(SHORT_NAMES[block])}{donde}.</p>"
            "<p>Elimine una de las dos y vuelva a intentarlo.</p>"
            f"{enlace_otra}"
            f'<p><a href="{html.escape(volver)}">Volver al documento</a></p>'
        )
        return _html(200, page("Aviso", body, advanced=sees_advanced(address)))
    if sale and result.status == "changed":
        return _back_to_month(store, year, month, form, vecina, moved=slug_of(block))
    return _back_to_month(store, year, month, form, entry_id)


class Route(NamedTuple):
    handler: Callable
    # True for a route that writes: it must carry a valid CSRF token no
    # matter what HTTP verb the request uses. Marking it here, on the route,
    # means a route added later either declares itself or defaults to
    # False -- unguarded but also read-only -- rather than being covered
    # only if whoever adds it remembers to special-case the method.
    mutates: bool


ROUTES: dict[str, Route] = {
    # "/entrada/nueva" is listed before the wildcard "/entrada/{id}" it would
    # otherwise also match (as an "id" of "nueva") -- _match() takes the
    # first hit in iteration order, so the literal route has to come first.
    "/entrada/nueva": Route(_handle_entrada_nueva, True),
    "/mes/{year}/{month}": Route(_handle_mes, False),
    "/entrada/{id}": Route(_handle_entrada, True),
    "/entrada/{id}/hoja": Route(_handle_asignar_hoja, True),
    "/entrada/{id}/bloque": Route(_handle_etiqueta, True),
    "/entradas/{id}": Route(_handle_entradas, True),
    "/guardar/{year}/{month}": Route(_handle_guardar, True),
    "/hoja/{reference}": Route(_handle_hoja, False),
    "/hoja/{reference}/girar": Route(_handle_girar, True),
    "/hoja/{reference}/fecha": Route(_handle_fecha, True),
    "/hoja/{reference}/linea": Route(_handle_linea_en_hoja, True),
    "/hoja/{reference}/vacia": Route(_handle_hoja_vacia, True),
    "/resumen": Route(_handle_resumen, False),
    "/mantenimiento/{year}/{month}": Route(_handle_mes_mantenimiento, False),
    "/mantenimiento": Route(_handle_mantenimiento, False),
    "/": Route(_handle_root, False),
}


def _split(path: str) -> list[str]:
    return [segment for segment in path.split("/") if segment != ""]


def _match(pattern: str, path: str) -> dict[str, str] | None:
    """Segment-by-segment match; a `{name}` segment accepts anything and is
    URL-decoded on capture, but the decoding happens *after* splitting, so an
    encoded slash inside one segment (``..%2f..%2fetc%2fpasswd``) stays one
    opaque value rather than growing new path segments.
    """
    pattern_segments = _split(pattern)
    path_segments = _split(path)
    if len(pattern_segments) != len(path_segments):
        return None
    params: dict[str, str] = {}
    for pattern_segment, path_segment in zip(
        pattern_segments, path_segments, strict=True
    ):
        if pattern_segment.startswith("{") and pattern_segment.endswith("}"):
            params[pattern_segment[1:-1]] = unquote(path_segment)
        elif pattern_segment != path_segment:
            return None
    return params


def handle(
    method: str,
    path: str,
    *,
    address: str,
    host: str | None = None,
    form: dict | None = None,
    store: EntryStore | None = None,
) -> Response:
    """Refuse, route, or 404 -- strictly in that order.

    The address is checked before ROUTES is even looked at (invariant: any
    path this function does not recognise yet still refuses an outside
    address, because it never gets past this line to be recognised or not).

    *host* is optional and, when omitted, is not checked at all: most of
    this suite calls handle() directly, below the transport layer, where
    there was never a Host header to begin with. serve() always supplies one.

    *path* may carry a query string (``/mes/2026/SEPTIEMBRE?hoja=...``); it is
    split off here, not by the caller, so a direct call in this module's own
    tests and a real request arriving through _dispatch_request go through
    the identical split. The query's values are merged into the same
    *params* dict a route's own segments populate -- a handler that wants
    "hoja" reads it exactly as it reads "year" or "month".
    """
    if not is_allowed(address):
        return _text(403, "Prohibido")
    if host is not None and not is_allowed_host(host):
        return _text(403, "Origen no permitido")
    # Maintenance: the colleague gets a notice instead of a page that may be
    # half updated, and nothing they send is written. The author, arriving
    # over Tailscale, still sees everything, to check the work before
    # switching it off.
    maintenance = os.path.exists(_maintenance_flag())
    if maintenance and not sees_advanced(address):
        return _maintenance_response(method)
    response = _route(method, path, address, form, store)
    if maintenance and response.content_type.startswith("text/html"):
        strip = with_maintenance_strip(response.body.decode("utf-8"))
        response = response._replace(body=strip.encode("utf-8"))
    return response


def _route(method: str, path: str, address: str, form: dict | None,
           store: EntryStore | None) -> Response:
    """The route for *path*, once handle() has let the request through."""
    form = form or {}
    split = urlsplit(path)
    clean_path = split.path
    query = {key: values[0] for key, values in parse_qs(split.query).items()}
    # Only one request's page work runs at a time. Two people use this page;
    # concurrency here buys nothing and costs a class of bug (see
    # _resolve_store). The server's threads only overlap the network waits.
    with _dispatch_lock:
        for pattern, route in ROUTES.items():
            matched = _match(pattern, clean_path)
            if matched is None:
                continue
            params = {**query, **matched}
            if route.mutates and not _check_csrf(address, form):
                return _text(403, "Token de seguridad inválido o ausente")
            real_store = _resolve_store(store) if store is not None else None
            return route.handler(method, params, form, real_store, address)

    return _text(404, "No encontrado")


def _maintenance_flag() -> str:
    """Where the maintenance switch lives: beside the database, in state/,
    which a deploy never touches, so the switch survives one."""
    return os.path.join(os.path.dirname(config.entry_db) or ".", "MANTENIMIENTO")


def _maintenance_response(method: str) -> Response:
    """The notice the colleague gets while the panel is being worked on.

    A page for a page load, which reloads itself and comes back on its own
    when the switch is off. Plain text for a submit, because the page's
    script shows a refused submit's body as its notice, and the typed text
    is still in the box on screen.
    """
    if method == "GET":
        response = _html(503, maintenance_page())
    else:
        response = _text(503, "Panel en mantenimiento: el cambio no se ha guardado. "
                              "Su texto sigue en pantalla; guárdelo cuando el panel "
                              "vuelva, en unos minutos.")
    return response._replace(headers={**response.headers, "Retry-After": "30"})


def _dispatch_request(
    method: str,
    headers,
    client_address: str,
    path: str,
    body: bytes,
    store: EntryStore,
) -> Response:
    """Turn one request's raw pieces into a Response, via handle().

    Factored out of serve() so the one thing a socket-free suite could not
    otherwise reach -- what actually happens when a request arrives with no
    Host header at all -- has somewhere to be tested. handle(host=None) is
    reserved for a caller that never spoke HTTP in the first place (this
    module's own test suite, calling handle() directly); a request that did
    arrive on the wire must not get that same pass just because it left Host
    out, so a missing header here becomes "", which is_allowed_host()
    correctly refuses rather than skips.
    """
    raw_body = body.decode("utf-8", errors="replace") if body else ""
    form = {key: values[0] for key, values in parse_qs(raw_body).items()}
    host = headers.get("Host", "") or ""
    # *path* still carries its query string here -- handle() does that split
    # itself now, the same way whether a request arrived on the wire or this
    # module's own tests called handle() directly with "?hoja=...".
    return handle(
        method, path, address=client_address, host=host, form=form, store=store
    )


# A socket that stops mid-request is dropped after this long, freeing its
# thread; a sheet image over a slow link still has ample time.
_SOCKET_TIMEOUT = 30


def make_server(port: int, store: EntryStore, host: str = "") -> ThreadingHTTPServer:
    """The dashboard's HTTP server, ready for serve_forever().

    A thread per request, so reading and writing one client's socket never
    holds up another's. September 30: a single client fetching the sheet
    images one by one over a slow link held the old single-threaded
    HTTPServer, and every other request -- the colleague's too -- waited
    more than thirty seconds. The page work itself still runs one request
    at a time under _dispatch_lock; only the network waits overlap.

    Call it from the thread that built *store*: the store is touched here
    once, so _resolve_store knows its file when a request thread cannot use
    the connection directly.
    """
    _resolve_store(store)

    class _RequestHandler(BaseHTTPRequestHandler):
        timeout = _SOCKET_TIMEOUT

        def _dispatch(self, method: str) -> None:
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else b""
                response = _dispatch_request(
                    method, self.headers, self.client_address[0], self.path, body, store
                )
            except Exception:
                # Whatever went wrong, the person on the other end gets a
                # plain apology, never a traceback with a table name in it.
                logging.exception("Error al atender la solicitud")
                response = _text(500, "Error interno. Inténtelo de nuevo más tarde.")
            self.send_response(response.status)
            self.send_header("Content-Type", response.content_type)
            self.send_header("Content-Length", str(len(response.body)))
            for key, value in response.headers.items():
                self.send_header(key, value)
            self.end_headers()
            if method != "HEAD":
                self.wfile.write(response.body)

        def do_GET(self) -> None:
            self._dispatch("GET")

        def do_POST(self) -> None:
            self._dispatch("POST")

        def log_message(self, log_format: str, *args) -> None:
            logging.info(f"{self.client_address[0]} - {log_format % args}")

    httpd = ThreadingHTTPServer((host, port), _RequestHandler)
    # A thread left waiting on a dead client must not keep the process up.
    httpd.daemon_threads = True
    return httpd


def serve(port: int, store: EntryStore) -> None:
    """Run the dashboard until the process is stopped."""
    make_server(port, store).serve_forever()


if __name__ == "__main__":
    # Its own unit, its own process: the dashboard dying never touches the
    # transcription pipeline, and the reverse.
    parser = argparse.ArgumentParser(description="NetTune review dashboard")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()

    with EntryStore(config.entry_db, recorder=nettune_feedback.recorder()) as store:
        serve(args.port, store)
