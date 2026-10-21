"""Turns entry dicts into the HTML of the review page. Nothing else.

No SQL, no file access, no network: every function here takes plain data
(dicts, strings, numbers) and returns a string. The database is EntryStore,
the network is the WSGI app in front of this module; neither belongs here.

The reader is the colleague who scans the sheets. He is not a developer and
works in Word all day, so the page has to look like an Office tool: a plain
palette, short and purposeful movement, and no vocabulary an office worker
would not already know. Every visible string is therefore Spanish -- code
identifiers are the only English left.

The author reads the same page over Tailscale and sees a second row of
numbers the colleague never does (see dashboard_auth.sees_advanced). summary()
is the only function that branches on that; everything else renders the same
page for both.
"""

import html
import re

from nettune.report.entry_store import sheet_order
from nettune.report.memoria_blocks import SHORT_NAMES, SLUGS, slug_of
from nettune.report.review_marks import MAINTENANCE_IMAGE_PREFIX, image_name, plain_ref

# Mirrors entry_store.review_line's own split of "20-09-2026 p39" into sheet
# and page: the label on the row and the sentence in the memoria should name
# the same sheet the same way.
_REF = re.compile(r"^(.*) p(\d+)$")


def _sheet_link_label(review_ref: str) -> str:
    """'20-09-2026 · página 39', or the scan name when no date could be read
    for this sheet.

    It used to read "Ver hoja del ...", which was right for a link sitting
    beside one line and wrong as the heading over a sheet's whole run: a
    heading names what is under it, it does not instruct.
    """
    match = _REF.match(plain_ref(review_ref))
    sheet, page = (match.group(1), match.group(2)) if match else (plain_ref(review_ref), "?")
    if not re.fullmatch(r"\d{2}-\d{2}-\d{4}", sheet):
        # Named after its scan because the date is unknown: say so, the way
        # the sheet list and the candidate buttons do.
        sheet = "sin fecha"
    return f"{sheet} \u00b7 página {page}"

# Exact palette, each colour declared once. No rgba, no opacity, no tint of a
# tint: a surface is a colour and a border is a colour, never a shade of one
# under it. Movement durations are the only other numbers this file is fussy
# about: nothing here may exceed 150ms, and prefers-reduced-motion turns all
# of it off, because the page's job is a document, not a demo.
STYLESHEET = """
:root {
  /* The width of the button column in every entry row. A fixed length on
     purpose: each row is its own grid, so a content-sized column would let
     rows disagree and the textareas would step in and out down the page. */
  --ancho-acciones: 172px;
  /* The tag chip's column: wide enough for "Electricidad", the longest. */
  --ancho-etiqueta: 90px;
  /* The tag filter bar's height, so a jump lands just below it. */
  --alto-filtro: 40px;
  /* Native controls -- textareas, scrollbars -- follow this, not the colour
     tokens. Without it they stayed light in the dark theme: white boxes and
     a white scrollbar strip down the middle of the page. */
  color-scheme: light;
  --page: #f3f2f1;
  --surface: #ffffff;
  --text: #1b1b1b;
  --muted: #5b5b5b;
  --border: #d1d1d1;
  --accent: #0f6cbd;
  --flag: #b8860b;
  --ok: #107c10;
  --error: #a4262c;
  --etiqueta-electricidad: #a35200;
  --etiqueta-ascensores: #5c2d91;
  --etiqueta-parking: #00666b;
  --etiqueta-otros: #5b5b5b;
}

[data-tema="oscuro"] {
  color-scheme: dark;
  --page: #1f1f1f;
  --surface: #2b2b2b;
  --text: #ededed;
  --muted: #a6a6a6;
  --border: #3d3d3d;
  --accent: #4aa3e0;
  --flag: #d8a12a;
  --ok: #4cb44c;
  --error: #e0646a;
  --etiqueta-electricidad: #f0a050;
  --etiqueta-ascensores: #b99be6;
  --etiqueta-parking: #3cc0c6;
  --etiqueta-otros: #a6a6a6;
}

* { box-sizing: border-box; }

html { height: 100%; }
body {
  /* A column that is exactly the viewport tall, so the three panels below
     can take the rest of it. The old layout hardcoded calc(100vh - 49px)
     for the command bar alone, which ignored the summary bar underneath it
     and pushed the panels past the bottom of the window -- the whole page
     scrolled instead of each panel scrolling on its own. */
  height: 100%;
  display: flex;
  flex-direction: column;
  margin: 0;
  background: var(--page);
  color: var(--text);
  font-family: "Segoe UI", system-ui, -apple-system, "Helvetica Neue", Arial, sans-serif;
  font-size: 14px;
}

a { color: var(--accent); }

main {
  flex: 1;
  /* min-height: 0 or a flex child refuses to shrink below its content, which
     is what makes an inner scroll area work at all. */
  min-height: 0;
  display: flex;
  flex-direction: column;
}
main > .resumen, main > .resumen-avanzado { flex: none; }

/* In the command bar the summary drops its own card -- the bar already is
   one -- and the advanced figures take a full-width second row, so turning
   them on grows the bar downwards instead of squeezing the tabs. */
.barra-comandos { flex-wrap: wrap; row-gap: 6px; }
.barra-comandos .resumen {
  padding: 0 12px 0 0;
  margin-right: 4px;
  background: none;
  border: none;
  border-right: 1px solid var(--border);
  border-radius: 0;
  gap: 12px;
}
.barra-comandos .resumen-cifra { font-size: 17px; }
.barra-comandos .resumen-detalle { gap: 12px; padding-left: 12px; font-size: 12px; }
.barra-comandos .barra-revisado { width: 80px; }
[data-avanzado="si"] .barra-comandos .resumen-avanzado {
  order: 99;
  flex-basis: 100%;
  margin-top: 0;
}

.barra-comandos {
  flex: none;
  display: flex;
  align-items: center;
  gap: 12px;
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  padding: 8px 12px;
}

.secciones { display: flex; gap: 4px; }
.secciones a {
  padding: 6px 12px;
  border-radius: 4px;
  text-decoration: none;
  color: var(--text);
}
.secciones a.activo { background: var(--page); color: var(--accent); }

.boton-icono, .boton-correcto, .boton-eliminar, .boton-revisar, .boton-guardar {
  background: var(--surface);
  color: var(--text);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 4px 10px;
  cursor: pointer;
  /* The one thing on the page that moves on hover, and only this fast. */
  transition: background-color 80ms ease, color 80ms ease;
}
.boton-icono:hover, .boton-correcto:hover, .boton-eliminar:hover, .boton-revisar:hover,
.boton-guardar:hover {
  background: var(--page);
}
.boton-guardar { color: var(--surface); background: var(--accent); border-color: var(--accent); }

/* Each toggle carries both of its icons and shows the one that says what the
   next click does. SVG, not a CSS content escape: "\\00ab" written inside a
   Python string is an octal escape, so the old rule served a NUL byte and the
   letters "ab" -- the stray characters on the button. */
.icono-cerrar-lateral, .icono-luna { display: block; }
.icono-abrir-lateral, .icono-sol { display: none; }
[data-lateral="cerrado"] .icono-cerrar-lateral { display: none; }
[data-lateral="cerrado"] .icono-abrir-lateral { display: block; }
[data-tema="oscuro"] .icono-luna { display: none; }
[data-tema="oscuro"] .icono-sol { display: block; }
#alternar-lateral, #alternar-tema {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 30px;
  padding: 0;
  color: var(--text);
}
.boton-guardar:hover { background: var(--accent); color: var(--surface); }

.disposicion {
  display: grid;
  /* The third column is auto, not a fixed length, so the pane's own width --
     whatever the resize handle or the remembered localStorage width set it
     to -- is what the grid honours, instead of snapping back to a track. */
  grid-template-columns: 240px minmax(0, 1fr) 6px auto;
  flex: 1;
  min-height: 0;
}
html[data-lateral="cerrado"] .disposicion,
.disposicion[data-lateral="cerrado"] { grid-template-columns: 0 minmax(0, 1fr) 6px auto; }
/* A zero-width column is not a hidden panel: the padding and the border
   survived it, so collapsing left a visible stub the sidebar's text then
   bled into. */
html[data-lateral="cerrado"] .panel-lateral,
.disposicion[data-lateral="cerrado"] .panel-lateral {
  padding: 0;
  border-right: none;
  visibility: hidden;
}

.panel-lateral {
  display: flex;
  flex-direction: column;
  min-height: 0;
  /* overflow-x only. It used to be overflow: hidden, which kept the collapse
     tidy but also clipped the list: a month with sixty-odd sheets showed the
     first few and no way to reach the rest. */
  overflow-x: hidden;
  border-right: 1px solid var(--border);
  background: var(--surface);
  padding: 12px;
  /* The sidebar is the only panel a person collapses by hand. */
  transition: width 150ms ease;
}
.panel-lateral h2, .panel-lateral h3 { flex: none; }

/* Months with entries, grouped by year. Capped so a long history scrolls
   inside itself instead of pushing the sheet list off the panel. */
.selector-meses {
  flex: none;
  max-height: 120px;
  overflow-y: auto;
  margin: -4px 0 12px;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--border);
  font-size: 12px;
}
.anio-meses { display: flex; gap: 8px; padding: 2px 0; }
.anio { flex: none; width: 34px; font-weight: 600; color: var(--muted); }
.meses { display: flex; flex-wrap: wrap; gap: 2px 8px; }
.meses a { color: var(--accent); text-decoration: none; }
.meses a:hover { text-decoration: underline; }
.mes-actual { font-weight: 600; color: var(--text); }

.panel-documento {
  overflow-y: auto;
  min-width: 0;
  padding: 16px;
}

/* Guardar in the command bar, right after the section tabs. */
.control-guardar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-left: 8px;
  padding-left: 12px;
  border-left: 1px solid var(--border);
}
.control-guardar form { margin: 0; }
.control-guardar .boton-guardar {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 5px 14px;
  font-weight: 600;
}
.control-guardar .icono-guardar { display: block; }

.entradas {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 4px 16px;
}

.panel-imagen {
  /* A flex column: the toolbar is a fixed first row and only the viewer
     under it scrolls. It used to be position: sticky inside the scrolling
     box, which holds on the vertical axis but slides away the moment a
     zoomed sheet is scrolled sideways. */
  display: flex;
  flex-direction: column;
  width: var(--ancho-imagen, 480px);
  min-width: 220px;
  /* Room to make this the main pane. The document can be read in a narrow
     column; the handwriting cannot. */
  max-width: 85vw;
  background: var(--surface);
  /* The viewer inside does the scrolling. */
  overflow: hidden;
}

/* The splitter between the document and the sheet. It replaces CSS
   resize: horizontal, which puts its grip on the bottom-right corner and
   grows the box rightwards -- and this is the rightmost column, so there was
   nowhere to grow and no way to take hold of the edge that matters, the
   left one. Dragging this left makes the sheet wider. */
.divisor-imagen {
  cursor: col-resize;
  background: var(--border);
  border-left: 2px solid var(--page);
  border-right: 2px solid var(--page);
  touch-action: none;
}
.divisor-imagen:hover,
.divisor-imagen:focus-visible,
.divisor-imagen.arrastrando {
  background: var(--accent);
  outline: none;
}
/* While dragging, the pointer may cross the image or a textarea; neither
   should select text or steal the cursor. */
body.redimensionando { cursor: col-resize; user-select: none; }
body.redimensionando .panel-imagen,
body.redimensionando .panel-documento { pointer-events: none; }

/* The part that scrolls, and the box every zoom figure is measured against. */
.visor-hoja {
  flex: 1;
  min-height: 0;
  overflow: auto;
}

.enlace-imagen {
  display: block;
  /* The link's only job is to wrap the image; it must not look like text. */
  border: none;
}

.imagen-hoja {
  /* Without the script: the panel's width. With it, the script sizes the
     sheet to fit whole in the viewer, and centres it. */
  width: 100%;
  max-width: 100%;
  display: block;
  margin: 0 auto;
  cursor: zoom-in;
  /* Evidence, not decoration: it must look like the paper in both themes,
     zoomed in or not. */
  filter: none;
}
/* Set by the script once the image is wider than the panel: the cursor says
   the image can be dragged, and grabbing says it is being dragged. */
.imagen-hoja.desplazable { cursor: grab; }
.imagen-hoja.agarrando { cursor: grabbing; }
/* No text selection while panning, or a drag highlights the page instead. */
.visor-hoja.arrastrando { user-select: none; }

.zoom-hoja {
  display: flex;
  gap: 4px;
  align-items: center;
  padding-right: 4px;
  margin-right: 4px;
  border-right: 1px solid var(--border);
}
.zoom-hoja button {
  width: 26px;
  height: 26px;
  padding: 0;
  font-size: 14px;
  line-height: 1;
  cursor: pointer;
  color: var(--text);
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 3px;
}
.zoom-hoja button:hover:not(:disabled) { border-color: var(--accent); color: var(--accent); }
.zoom-hoja button:disabled { color: var(--border); cursor: default; }
.nivel-zoom {
  min-width: 46px;
  padding: 0 2px;
  font-size: 12px;
  text-align: center;
  color: var(--muted);
  font-variant-numeric: tabular-nums;
  cursor: pointer;
  background: none;
  border: none;
}

/* A grid, not a flex row. Flex let the row overflow -- the textarea would
   not shrink below its 400px floor and the sheet link would not shrink at
   all -- so on a row that had a link the link was drawn over the "Guardar
   línea" button. Named areas give everything a cell of its own, and the
   fixed outer columns mean every textarea in the document is exactly the
   same width instead of each row sizing itself around whatever it contains.
   One compact line per entry: the old three-line box and stacked buttons
   took about 116px a line, so a sheet of ten lines did not fit on screen. */
.fila-entrada {
  display: grid;
  grid-template-columns: 14px minmax(0, 1fr) var(--ancho-acciones);
  grid-template-areas:
    "marca texto acciones"
    "marca guardar acciones";
  align-items: center;
  column-gap: 10px;
  padding: 4px 8px 4px 10px;
  border-bottom: 1px solid var(--border);
  margin: 0;
  transition: background-color 80ms ease;
}
.fila-entrada:hover { background: color-mix(in srgb, var(--page) 60%, var(--surface)); }
/* Mantenimiento: the tag gets its own column, so every chip lines up and its
   menu opens from a known place. */
.fila-entrada.con-etiqueta {
  grid-template-columns: 14px var(--ancho-etiqueta) minmax(0, 1fr) var(--ancho-acciones);
  grid-template-areas:
    "marca etiqueta texto acciones"
    "marca etiqueta guardar acciones";
}
/* A stripe in the tag's colour down the left edge: the month reads as
   colour bands by subheading before a single chip is read. */
.fila-entrada[data-etiqueta="electricidad"] { box-shadow: inset 3px 0 0 var(--etiqueta-electricidad); }
.fila-entrada[data-etiqueta="ascensores"] { box-shadow: inset 3px 0 0 var(--etiqueta-ascensores); }
.fila-entrada[data-etiqueta="parking"] { box-shadow: inset 3px 0 0 var(--etiqueta-parking); }
.fila-entrada[data-etiqueta="otros"] { box-shadow: inset 3px 0 0 var(--etiqueta-otros); }
.fila-entrada > .marca-dudosa { grid-area: marca; align-self: center; }
/* display: contents so the textarea and its button land in the grid cells
   above, while still belonging to the form that submits them. */
.forma-texto { display: contents; }
/* Guardar línea only where a line is being worked on: focus-within needs no
   script, so the button is there for anyone typing, with or without it. The
   text's own form, not the whole row: focusing the tag chip grew the row
   between mousedown and mouseup, and the click missed the chip. */
.forma-texto > .boton-icono {
  grid-area: guardar;
  display: none;
  justify-self: end;
  margin: 4px 0 2px;
  padding: 2px 10px;
  font-size: 12px;
}
.forma-texto:focus-within > .boton-icono,
.fila-entrada:has(.sin-guardar) .forma-texto > .boton-icono {
  display: inline-block;
}
.acciones-entrada { grid-area: acciones; }
.fila-entrada:last-child { border-bottom: none; }

.marca-dudosa { grid-area: marca; align-self: center; }
/* display: contents so the textarea and its button land in the grid cells
   above, while still belonging to the form that submits them. */
.forma-texto { display: contents; }
.forma-texto > .boton-icono { grid-area: guardar; }
.acciones-entrada { grid-area: acciones; }
.fila-entrada:last-child { border-bottom: none; }

.marca-dudosa {
  flex: none;
  width: 14px;
  height: 14px;
  margin-top: 4px;
  color: var(--flag);
  /* Clears the moment a person confirms or edits the line, and only that. */
  transition: opacity 120ms ease;
}
.marca-dudosa.resuelta { opacity: 0; }

.texto-entrada {
  grid-area: texto;
  /* The grid column decides the width, identically for every row, so the
     box never has to be dragged wider one line at a time. */
  width: 100%;
  min-width: 0;
  box-sizing: border-box;
  /* As tall as its text and no taller: most lines are one line. rows="3"
     stays in the markup as the height for a browser without field-sizing,
     where the page's script sizes the box instead. */
  field-sizing: content;
  min-height: 1.9em;
  resize: vertical;
  padding: 3px 6px;
  /* A filled box rather than a bordered one: still plainly a place to type,
     without a frame around every one of a hundred lines. */
  color: var(--text);
  background: var(--page);
  border: 1px solid transparent;
  border-radius: 4px;
  font: inherit;
  line-height: 1.4;
  /* Deliberately no transition: text that shifts while being edited is
     worse than text that does not. */
}
.fila-entrada:hover .texto-entrada { border-color: var(--border); }
.texto-entrada:focus { outline: none; border-color: var(--accent); background: var(--surface); }
/* Typed into, not yet saved -- the same cue Word gives with its title bar,
   placed on the line itself because this document has hundreds of them. */
.texto-entrada.sin-guardar { border-color: var(--flag); border-left-width: 3px; }
.estado-guardado { font-size: 12px; color: var(--flag); white-space: nowrap; }

/* A short notice for what the server said, instead of a page of its own. */
.aviso-mantenimiento {
  padding: 6px 16px;
  background: var(--flag);
  color: var(--surface);
  font-weight: 600;
  text-align: center;
}

.aviso-flotante {
  position: fixed;
  left: 50%;
  bottom: 20px;
  z-index: 10;
  max-width: min(560px, calc(100vw - 32px));
  padding: 10px 16px;
  font-size: 13px;
  color: var(--surface);
  background: var(--text);
  border-radius: 4px;
  opacity: 0;
  pointer-events: none;
  transform: translate(-50%, 8px);
  transition: opacity 150ms ease, transform 150ms ease;
}
.aviso-flotante.visible { opacity: 1; transform: translate(-50%, 0); }
body.ocupado, body.ocupado button { cursor: progress; }
/* A line just added, marked briefly so the eye finds it without a jump. */
.fila-entrada.recien-anadida { background: var(--page); box-shadow: inset 3px 0 0 var(--accent); }
.estado-guardado:empty { display: none; }

.acciones-entrada { display: flex; gap: 4px; justify-content: flex-end; align-items: center; }
.acciones-entrada > button {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 8px;
  font-size: 13px;
  white-space: nowrap;
}
.acciones-entrada svg { display: block; }
.boton-correcto:hover { color: var(--ok); border-color: var(--ok); }
/* Eliminar is an icon: quieter than Correcto, which is what most lines get,
   and red only when the pointer is on it. */
.boton-eliminar { color: var(--muted); padding: 3px 6px; }
.boton-eliminar:hover { color: var(--error); border-color: var(--error); }
/* Marcar para revisar: as quiet as Eliminar, in the flag's colour on hover. */
.boton-revisar { color: var(--muted); padding: 3px 6px; }
.boton-revisar:hover { color: var(--flag); border-color: var(--flag); }
/* Read out by screen readers, not drawn. */
.solo-lector {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
}

/* The band that opens each sheet's run of lines. Not sticky: with one per
   sheet, sticky headings piled up at the top of the pane as it scrolled. */
.cabecera-hoja {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 10px -16px 0;
  padding: 5px 16px;
  font-size: 12px;
  font-weight: 600;
  text-decoration: none;
  color: var(--accent);
  background: var(--page);
  border-top: 1px solid var(--border);
  border-bottom: 1px solid var(--border);
}
.cabecera-hoja { scroll-margin-top: 8px; }
.cabecera-hoja:hover { background: var(--border); }
.cabecera-hoja.actual { color: var(--surface); background: var(--accent); }
.cabecera-hoja.sin-referencia {
  flex-wrap: wrap;
  color: var(--flag);
  font-weight: 600;
}
.cabecera-hoja .candidata { color: var(--accent); font-weight: 600; }
.cabecera-hoja .candidata.actual { text-decoration: underline; }
.cabecera-hoja .o { color: var(--muted); font-weight: 400; }

/* A sheet with no lines: a note, and a box to start it. */
.hoja-vacia { padding: 4px 0 10px; }
.hoja-vacia p { margin: 4px 0 6px 22px; font-size: 12px; color: var(--muted); }
.hoja-vacia .forma-anadir { margin-top: 0; }

/* Settling a sheet's date, under its heading. */
.fecha-hoja { margin: 0 0 4px; padding: 6px 16px; font-size: 12px; }
.panel-imagen > .fecha-hoja {
  flex: none;
  margin: 0;
  padding: 6px 8px;
  border-bottom: 1px solid var(--border);
}
.fecha-hoja.dudosa, .fecha-hoja.sin-fecha {
  background: var(--surface);
  border-bottom: 1px dashed var(--flag);
}
.fecha-hoja .pregunta { display: block; margin-bottom: 4px; color: var(--flag); font-weight: 600; }
.opciones-fecha { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
.opciones-fecha form { margin: 0; display: flex; gap: 6px; align-items: center; }
.opciones-fecha input[type="date"] {
  padding: 2px 4px;
  font: inherit;
  color: var(--text);
  background: var(--page);
  border: 1px solid var(--border);
  border-radius: 3px;
}
.fecha-hoja.cambiar > summary {
  list-style: none;
  cursor: pointer;
  color: var(--muted);
  font-size: 11px;
}
.fecha-hoja.cambiar > summary::-webkit-details-marker { display: none; }
.fecha-hoja.cambiar > summary:hover { color: var(--accent); }
.fecha-hoja.cambiar[open] > summary { margin-bottom: 4px; }

/* Choosing a page for a line that lost it: a third row under the text. */
.fila-entrada.sin-hoja {
  grid-template-areas:
    "marca texto acciones"
    "marca guardar acciones"
    "marca asignar asignar";
}
.fila-entrada.sin-hoja.con-etiqueta {
  grid-template-areas:
    "marca etiqueta texto acciones"
    "marca etiqueta guardar acciones"
    "marca asignar asignar asignar";
}
.asignar-hoja {
  grid-area: asignar;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  font-size: 12px;
}
.asignar-hoja form { margin: 0; }
.asignar-hoja .pregunta { color: var(--flag); font-weight: 600; }
.boton-asignar {
  padding: 3px 10px;
  font: inherit;
  font-size: 12px;
  cursor: pointer;
  color: var(--accent);
  background: var(--surface);
  border: 1px solid var(--accent);
  border-radius: 3px;
}
.boton-asignar:hover { color: var(--surface); background: var(--accent); }
.titulo-bloque + .cabecera-hoja { margin-top: 4px; }

/* Adding a line. Quiet until wanted: a hairline gap between rows that shows
   its label on hover or focus, so 170 of them do not shout down the page. */
.anadir-linea { margin: 0; }
.anadir-linea > summary {
  list-style: none;
  display: flex;
  align-items: center;
  gap: 6px;
  height: 14px;
  margin-left: 22px;
  font-size: 11px;
  color: transparent;
  cursor: pointer;
}
.anadir-linea > summary::-webkit-details-marker { display: none; }
.anadir-linea > summary .mas {
  width: 14px;
  height: 14px;
  line-height: 12px;
  text-align: center;
  color: var(--muted);
  border: 1px solid var(--border);
  border-radius: 50%;
  background: var(--surface);
  opacity: 0;
}
.anadir-linea > summary:hover,
.anadir-linea > summary:focus-visible,
.anadir-linea[open] > summary { color: var(--accent); outline: none; }
.anadir-linea > summary:hover .mas,
.anadir-linea > summary:focus-visible .mas,
.anadir-linea[open] > summary .mas {
  opacity: 1;
  color: var(--accent);
  border-color: var(--accent);
}
.forma-anadir {
  display: grid;
  grid-template-columns: minmax(0, 1fr) var(--ancho-acciones);
  gap: 8px;
  margin: 4px 0 8px 22px;
}
.texto-nuevo {
  width: 100%;
  min-height: 3em;
  resize: vertical;
  padding: 4px 6px;
  font: inherit;
  color: var(--text);
  background: var(--page);
  border: 1px dashed var(--accent);
  border-radius: 3px;
}
.texto-nuevo:focus { outline: none; border-style: solid; }
.forma-anadir .boton-icono { align-self: start; }

/* The row belonging to the sheet on screen reads as part of it, the same
   way the sidebar already marks that sheet selected. */
.fila-entrada.hoja-actual { background: var(--page); }
.entradas { position: relative; }

.lista-hojas {
  list-style: none;
  margin: 0;
  padding: 0;
  /* The list is the part that scrolls; the month and the heading stay put. */
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}
.lista-hojas li { padding: 1px 0; }
/* One line per sheet: state symbol, the sheet, and how many lines are left. */
.lista-hojas .hoja-pendiente {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 6px;
  border-radius: 3px;
  text-decoration: none;
  color: var(--text);
}
.lista-hojas .hoja-pendiente:hover { background: var(--page); }
.hoja-pendiente.seleccionada {
  background: var(--page);
  font-weight: 600;
  box-shadow: inset 3px 0 0 var(--accent);
}
.estado-hoja { flex: none; display: flex; }
.estado-hoja.pendiente { color: var(--flag); }
.estado-hoja.revisada { color: var(--ok); }
.estado-hoja.vacia { color: var(--muted); }
.hoja-pendiente.vacia .nombre-en-lista { color: var(--muted); font-style: italic; }
.nombre-en-lista {
  flex: 1;
  min-width: 0;
  font-size: 13px;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.hoja-pendiente.revisada .nombre-en-lista { color: var(--muted); }
.cuenta-dudas {
  flex: none;
  min-width: 20px;
  padding: 0 6px;
  font-size: 11px;
  font-weight: 600;
  line-height: 18px;
  text-align: center;
  color: var(--surface);
  background: var(--flag);
  border-radius: 9px;
}
.leyenda-hojas {
  display: flex;
  gap: 12px;
  flex: none;
  margin: -2px 0 8px;
  font-size: 11px;
  color: var(--muted);
}
.leyenda-hojas span { display: flex; align-items: center; gap: 4px; }

.titulo-bloque {
  margin: 16px 0 4px;
  padding-top: 8px;
  color: var(--muted);
  font-size: 13px;
  font-weight: 600;
  border-top: 1px solid var(--border);
}
.titulo-bloque:first-child { margin-top: 4px; padding-top: 0; border-top: none; }

.sin-hoja { padding: 12px; color: var(--muted); }

/* The sheet panel's own little toolbar. Sticky because the panel scrolls
   when the image is zoomed, and the buttons are no use scrolled off. */
.barra-hoja {
  flex: none;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 6px 8px;
  background: var(--surface);
  border-bottom: 1px solid var(--border);
}
.nombre-hoja {
  font-size: 12px;
  color: var(--muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.giros { display: flex; gap: 4px; flex-shrink: 0; align-items: center; }
.giros form { margin: 0; }

/* Por revisar / Todas. Two links, so the choice survives a reload and can be
   bookmarked, rather than living in a script. */
.modo-hojas {
  display: flex;
  gap: 4px;
  flex: none;
  margin-bottom: 8px;
}
.modo-hojas a {
  flex: 1;
  padding: 3px 6px;
  font-size: 12px;
  text-align: center;
  text-decoration: none;
  color: var(--muted);
  border: 1px solid var(--border);
  border-radius: 3px;
}
.modo-hojas a.activo {
  color: var(--surface);
  background: var(--accent);
  border-color: var(--accent);
}

.paso-hoja {
  display: flex;
  gap: 4px;
  align-items: center;
  padding-right: 4px;
  margin-right: 4px;
  border-right: 1px solid var(--border);
}
/* Scoped to the arrows. The position counter is a span in this group too,
   and an unscoped ".paso-hoja span" boxed it into 26px and clipped it. */
.paso-hoja > a, .paso-hoja > span[aria-hidden] {
  width: 26px;
  height: 26px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 15px;
  text-decoration: none;
  color: var(--text);
  border: 1px solid var(--border);
  border-radius: 3px;
}
.paso-hoja a:hover { border-color: var(--accent); color: var(--accent); }
/* The end of the batch is shown as a dead button, not a missing one, so the
   toolbar does not change width as you walk through it. */
.paso-hoja > span[aria-hidden] { color: var(--border); }
.posicion-hoja { font-size: 12px; color: var(--muted); white-space: nowrap; }
.boton-girar {
  /* The glyphs are arrows, not text, so they need a line box that does not
     shift them off centre the way the inherited one does. */
  width: 26px;
  height: 26px;
  padding: 0;
  font-size: 15px;
  line-height: 1;
  cursor: pointer;
  color: var(--text);
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 3px;
}
.boton-girar:hover { border-color: var(--accent); color: var(--accent); }

/* One card, one hierarchy: the count the colleague acts on reads largest,
   everything else sits behind a hairline as supporting detail -- the same
   surface-and-border language as the sidebar and the entry rows. */
.resumen {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 8px 16px;
}

.resumen-principal {
  display: flex;
  align-items: baseline;
  gap: 6px;
}

.resumen-cifra {
  font-size: 20px;
  font-weight: 600;
  color: var(--text);
}

.resumen-etiqueta { color: var(--muted); font-size: 13px; }

.resumen-detalle {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
  padding-left: 16px;
  border-left: 1px solid var(--border);
  color: var(--muted);
  font-size: 13px;
}

/* Off unless the switch is on. Rendered only for an address entitled to it
   in the first place -- see dashboard_auth.sees_advanced -- so this hides
   nothing the browser was not already trusted with. */
.resumen-avanzado { display: none; }
[data-avanzado="si"] .resumen-avanzado {
  display: flex;
  align-items: stretch;
  gap: 16px;
  flex-wrap: wrap;
  margin-top: 8px;
  padding: 10px 16px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 4px;
}

.gasto-avanzado {
  display: grid;
  grid-template-columns: auto auto;
  align-items: baseline;
  gap: 0 6px;
  padding-right: 16px;
  border-right: 1px solid var(--border);
}
.gasto-avanzado .dato-etiqueta { grid-column: 1 / -1; }
.gasto-cifra { font-size: 18px; font-weight: 600; color: var(--text); }
.gasto-tope { font-size: 12px; color: var(--muted); }
.barra-gasto {
  grid-column: 1 / -1;
  width: 100%;
  height: 4px;
  margin-top: 5px;
  background: var(--border);
  border-radius: 2px;
  overflow: hidden;
}
.barra-gasto-relleno { height: 100%; background: var(--accent); }

.datos-avanzados {
  display: flex;
  align-items: center;
  gap: 20px;
  flex-wrap: wrap;
}
.dato-avanzado { display: flex; flex-direction: column; gap: 1px; }
.dato-etiqueta {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: .04em;
  color: var(--muted);
}
.dato-valor { font-size: 13px; color: var(--text); font-variant-numeric: tabular-nums; }

/* The switch itself, in the command bar. Only rendered for an entitled
   address, so its absence is the LAN's normal state. */
.interruptor-avanzado {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--muted);
  cursor: pointer;
  background: none;
  border: none;
  padding: 2px 4px;
}
.interruptor-avanzado .carril {
  width: 28px;
  height: 15px;
  padding: 2px;
  background: var(--border);
  border-radius: 8px;
  transition: background 120ms ease;
}
.interruptor-avanzado .perilla {
  display: block;
  width: 11px;
  height: 11px;
  background: var(--surface);
  border-radius: 50%;
  transition: transform 120ms ease;
}
[data-avanzado="si"] .interruptor-avanzado { color: var(--accent); }
[data-avanzado="si"] .interruptor-avanzado .carril { background: var(--accent); }
[data-avanzado="si"] .interruptor-avanzado .perilla { transform: translateX(13px); }

.barra-revisado {
  width: 120px;
  height: 6px;
  background: var(--border);
  border-radius: 3px;
  overflow: hidden;
}
.barra-revisado-relleno { height: 100%; background: var(--accent); }

.estado-ok { color: var(--ok); }
.estado-error { color: var(--error); }

.seccion-mantenimiento {
  display: flex;
  align-items: center;
  justify-content: center;
  /* flex: 1 inside <main>, not a viewport calculation: the card centres in
     whatever room is left under the bars, whatever height they turn out to
     be. */
  flex: 1;
  min-height: 0;
  padding: 24px;
}

/* Mantenimiento: one tag per line, and a bar to show one tag at a time. */
/* Stays at the top of the document as the month scrolls past. top: -16px
   cancels the panel's own padding: at 0 it stopped 16px down, with lines
   scrolling through the gap above it. The card's width and colour, so the
   lines pass under it; over the rows and sheet headings, under an open tag
   menu (z-index 20) so a menu near the top is never cut off. */
.filtro-etiquetas {
  position: sticky;
  top: -16px;
  z-index: 15;
  display: flex; flex-wrap: wrap; gap: 6px;
  margin: -4px -16px 8px;
  padding: 8px 16px;
  font-size: 13px;
  background: var(--surface);
  border-bottom: 1px solid var(--border);
}
/* A shadow only once something is under it, where the browser can tell. */
@supports (animation-timeline: scroll()) {
  .filtro-etiquetas {
    animation: sombra-filtro linear both;
    animation-timeline: scroll(nearest block);
    animation-range: 0 24px;
  }
  @keyframes sombra-filtro {
    from { box-shadow: 0 0 0 transparent; }
    to { box-shadow: 0 4px 8px -4px rgb(0 0 0 / 0.25); }
  }
}
.aviso-movida {
  margin: 0 0 8px;
  padding: 4px 10px;
  font-size: 12px;
  color: var(--muted);
  background: var(--page);
  border-radius: 4px;
}
/* A sheet opened from the list, or a line returned to after a save, lands
   just below the bar instead of behind it. */
.entradas:has(.filtro-etiquetas) .cabecera-hoja,
.entradas:has(.filtro-etiquetas) .fila-entrada {
  scroll-margin-top: calc(var(--alto-filtro) + 8px);
}
.filtro-etiquetas a, .filtro-etiquetas .actual {
  padding: 2px 10px; border: 1px solid var(--border); border-radius: 999px;
  color: var(--text); text-decoration: none;
}
.filtro-etiquetas .actual { border-color: var(--accent); color: var(--accent); font-weight: 600; }
.filtro-etiquetas .cuenta { color: var(--muted); font-variant-numeric: tabular-nums; }
.etiqueta-linea { grid-area: etiqueta; position: relative; align-self: center; }
.etiqueta-linea > summary { list-style: none; cursor: pointer; }
.etiqueta-linea > summary::-webkit-details-marker { display: none; }
.etiqueta, .opcion-etiqueta {
  display: inline-block; padding: 1px 8px; border: 1px solid currentColor;
  border-radius: 999px; font-size: 12px; background: var(--surface);
}
/* Opens to the right, into the document: anchored at its right edge it
   opened left, under the sidebar, where it could not be used. */
.menu-etiquetas {
  position: absolute; z-index: 20; left: 0; top: 100%; margin-top: 4px; padding: 6px;
  min-width: max-content; box-shadow: 0 4px 12px rgb(0 0 0 / 0.18);
  display: flex; flex-direction: column; gap: 4px;
  background: var(--surface); border: 1px solid var(--border); border-radius: 6px;
}
.opcion-etiqueta { cursor: pointer; text-align: left; }
.opcion-etiqueta[aria-pressed="true"] { font-weight: 600; }
.etiqueta-electricidad { color: var(--etiqueta-electricidad); }
.etiqueta-ascensores { color: var(--etiqueta-ascensores); }
.etiqueta-parking { color: var(--etiqueta-parking); }
.etiqueta-otros { color: var(--etiqueta-otros); }
.aviso-futuro {
  max-width: 460px;
  padding: 32px;
  text-align: center;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 6px;
}
.icono-futuro { font-size: 34px; line-height: 1; opacity: .55; }
.aviso-futuro h2 {
  margin: 12px 0 10px;
  font-size: 17px;
  font-weight: 600;
  color: var(--text);
}
.aviso-futuro p { margin: 0 0 10px; font-size: 13px; color: var(--muted); }
.nota-futuro { padding-top: 10px; border-top: 1px solid var(--border); }
.enlace-volver {
  display: inline-block;
  margin-top: 6px;
  font-size: 13px;
  color: var(--accent);
}

/* Below this the three panels stop fitting side by side, so they stack and
   the page scrolls as one instead of three panes each too narrow to use. */
@media (max-width: 1100px) {
  .disposicion,
  .disposicion[data-lateral="cerrado"] {
    grid-template-columns: minmax(0, 1fr);
    grid-auto-rows: min-content;
    overflow-y: auto;
  }
  /* Stacked panes have no shared edge to drag. */
  .divisor-imagen { display: none; }
  .panel-lateral {
    border-right: none;
    border-bottom: 1px solid var(--border);
  }
  .lista-hojas { max-height: 40vh; }
  .panel-documento { overflow-y: visible; }
  /* The stacked layout scrolls as a whole, with no padding to cancel. */
  .filtro-etiquetas { top: 0; }
  .panel-imagen {
    width: auto !important;
    max-width: none;
    resize: none;
    height: 80vh;
    border-left: none;
    border-top: 1px solid var(--border);
  }
  html[data-lateral="cerrado"] .panel-lateral,
  .disposicion[data-lateral="cerrado"] .panel-lateral { display: none; }
}

/* Narrower still -- a phone, or the window at a quarter of the screen. The
   buttons go under the text rather than squeezing it to nothing. */
@media (max-width: 700px) {
  .fila-entrada {
    grid-template-columns: 14px minmax(0, 1fr);
    grid-template-areas:
      "marca texto"
      ".     guardar"
      ".     acciones";
  }
  .forma-texto > .boton-icono, .acciones-entrada { justify-self: stretch; }
}

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    transition: none !important;
    animation: none !important;
  }
}
"""

# Buttons, not a form: zooming changes nothing on the server. They start
# hidden and the script reveals them, so a browser with no script never shows
# a control that would do nothing -- there the anchor around the image still
# opens the full-resolution scan on its own page, which is the fallback.
_CONTROLES_ZOOM = (
    '<div class="zoom-hoja" id="zoom-hoja" hidden>'
    '<button type="button" id="zoom-menos" title="Alejar">&minus;</button>'
    '<button type="button" class="nivel-zoom" id="nivel-zoom" '
    'title="Ajustar a la ventana">Ajustar</button>'
    '<button type="button" id="zoom-mas" title="Acercar">+</button>'
    '</div>'
)

# Off by default: these are the author's numbers, and nothing here is needed
# to check a memoria against the paper.
_INTERRUPTOR_AVANZADO = (
    '<button type="button" id="alternar-avanzado" class="interruptor-avanzado" '
    'aria-pressed="false" title="Mostrar u ocultar las cifras técnicas">'
    '<span class="carril"><span class="perilla"></span></span>'
    'Modo avanzado</button>'
)

_SVG = ('<svg viewBox="0 0 20 20" width="18" height="18" aria-hidden="true" '
        'focusable="false" fill="none" stroke="currentColor" stroke-width="1.6" '
        'stroke-linecap="round" stroke-linejoin="round" class="{clase}">{trazo}</svg>')

# A floppy disk: still the one picture everybody reads as "save".
_ICONO_GUARDAR = _SVG.format(
    clase="icono-guardar",
    trazo='<path d="M4 3h9.5L17 6.5V16a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1Z"/>'
          '<path d="M6.5 3v4h6V3M6 17v-5.5h8V17"/>',
)

# A moon in the light theme (the next click goes dark), a sun in the dark one.
_ICONO_TEMA = (
    _SVG.format(clase="icono-luna",
                trazo='<path d="M16.5 12.5A7 7 0 0 1 7.5 3.5a7 7 0 1 0 9 9Z"/>')
    + _SVG.format(clase="icono-sol",
                  trazo='<circle cx="10" cy="10" r="3.5"/>'
                        '<path d="M10 1.5v2M10 16.5v2M1.5 10h2M16.5 10h2'
                        'M4 4l1.4 1.4M14.6 14.6 16 16M4 16l1.4-1.4M14.6 5.4 16 4"/>')
)

# A panel with its sidebar, and an arrow saying which way the next click moves it.
_ICONO_LATERAL = (
    _SVG.format(clase="icono-cerrar-lateral",
                trazo='<rect x="2.5" y="3.5" width="15" height="13" rx="1.5"/>'
                      '<path d="M7.5 3.5v13M12.5 8l-2 2 2 2"/>')
    + _SVG.format(clase="icono-abrir-lateral",
                  trazo='<rect x="2.5" y="3.5" width="15" height="13" rx="1.5"/>'
                        '<path d="M7.5 3.5v13M10.5 8l2 2-2 2"/>')
)

# A tick: the sheet has nothing left to check.
_ICONO_REVISADA = (
    '<svg viewBox="0 0 14 14" width="14" height="14" aria-hidden="true" '
    'focusable="false"><path d="M2.5 7.5 5.5 10.5 11.5 3.5" fill="none" '
    'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
    'stroke-linejoin="round"/></svg>'
)

# An empty dashed circle: a sheet with no lines on it.
_ICONO_VACIA = (
    '<svg viewBox="0 0 14 14" width="14" height="14" aria-hidden="true" '
    'focusable="false"><circle cx="7" cy="7" r="4.5" fill="none" '
    'stroke="currentColor" stroke-width="1.6" stroke-dasharray="2 1.6"/></svg>'
)

_ICONO_MARCA = (
    '<svg viewBox="0 0 14 14" width="14" height="14" aria-hidden="true" '
    'focusable="false"><path d="M7 1 13 13 1 13Z" fill="currentColor"/></svg>'
)

_ICONO_CORRECTO = (
    '<svg viewBox="0 0 14 14" width="13" height="13" aria-hidden="true" focusable="false">'
    '<path d="M2 7.5 5.5 11 12 3.5" fill="none" stroke="currentColor" stroke-width="1.8" '
    'stroke-linecap="round" stroke-linejoin="round"/></svg>'
)
_ICONO_PAPELERA = (
    '<svg viewBox="0 0 14 14" width="14" height="14" aria-hidden="true" focusable="false">'
    '<path d="M2.5 4h9M5.5 4V2.5h3V4M3.5 4l.6 7.6c0 .5.4.9.9.9h4c.5 0 .9-.4.9-.9L10.5 4'
    'M6 6.5v3.5M8 6.5v3.5" fill="none" stroke="currentColor" stroke-width="1.2" '
    'stroke-linecap="round" stroke-linejoin="round"/></svg>'
)

# Runs in <head>, before the first paint. The theme, the sidebar and the
# sheet panel's width used to be applied by the script at the end of the
# body, so every page load drew the light theme and default layout first and
# then switched: the white flash, and the panel jumping, on every full load.
_PRIMER_PINTADO = (
    "(function(){try{var r=document.documentElement,s=window.localStorage;"
    "var t=s.getItem('memoria-tema');if(!t){t=window.matchMedia&&"
    "window.matchMedia('(prefers-color-scheme: dark)').matches?'oscuro':'claro';}"
    "r.setAttribute('data-tema',t);"
    "var l=s.getItem('memoria-lateral');if(l){r.setAttribute('data-lateral',l);}"
    "var a=s.getItem('memoria-imagen-ancho-2');if(a){r.style.setProperty('--ancho-imagen',a);}"
    "}catch(e){}})();"
)

# The theme, sidebar and sheet-panel width are per-browser, not per-account --
# there is no account. A first visit follows the operating system; after
# that, whatever the person last chose sticks, in this browser only.
_SCRIPT = """
(function () {
  var raiz = document.documentElement;
  var TEMA_CLAVE = 'memoria-tema';
  var LATERAL_CLAVE = 'memoria-lateral';
  var ANCHO_IMAGEN_CLAVE = 'memoria-imagen-ancho-2';

  function leer(clave) {
    try { return window.localStorage.getItem(clave); } catch (e) { return null; }
  }
  function escribir(clave, valor) {
    try { window.localStorage.setItem(clave, valor); } catch (e) { /* sin almacenamiento */ }
  }

  var tema = leer(TEMA_CLAVE);
  if (!tema) {
    tema = (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches)
      ? 'oscuro' : 'claro';
  }
  raiz.setAttribute('data-tema', tema);

  var lateral = leer(LATERAL_CLAVE) || 'abierto';
  raiz.setAttribute('data-lateral', lateral);
  document.querySelectorAll('.disposicion').forEach(function (nodo) {
    nodo.setAttribute('data-lateral', lateral);
  });

  // Saving like a word processor. Each line is its own form and a browser
  // only submits the one that was pressed, so whichever form is submitted
  // carries every other edited box with it as texto-{id}, and the server
  // applies them first (dashboard._apply_pending_edits). Ctrl+S (Cmd+S on a
  // Mac) submits Guardar: every line, then the .docx.
  //
  // And none of it reloads the page. Every button used to post and let the
  // browser follow the redirect, which rebuilt the whole page and jumped to
  // #entrada-N -- putting the line that was just pressed at the very top of
  // the pane, so a click in the middle of the screen looked like a jump to
  // somewhere else. Now the form is sent in the background, the server's
  // answer is the same page it always was, and only the parts that change
  // are swapped in, with the pane left exactly where it was. With no script
  // the forms still post and redirect as before.
  var enviando = false;

  function cajasActuales() {
    return [].slice.call(document.querySelectorAll('.texto-entrada'));
  }
  function editadas() {
    return cajasActuales().filter(function (caja) { return caja.value !== caja.defaultValue; });
  }
  function pintarPendientes() {
    var n = 0;
    cajasActuales().forEach(function (caja) {
      var cambiada = caja.value !== caja.defaultValue;
      caja.classList.toggle('sin-guardar', cambiada);
      if (cambiada) { n++; }
    });
    var estado = document.getElementById('estado-guardado');
    if (estado) {
      estado.textContent = n === 0 ? ''
        : (n === 1 ? '1 línea sin guardar' : n + ' líneas sin guardar');
    }
  }
  // Delegated, so boxes swapped in later are tracked too.
  document.addEventListener('input', function (evento) {
    if (evento.target.classList && evento.target.classList.contains('texto-entrada')) {
      pintarPendientes();
    }
  });

  function adjuntarEditadas(formulario) {
    var puestos = [];
    editadas().forEach(function (caja) {
      // A box inside the submitted form already travels with it.
      if (formulario.contains(caja)) { return; }
      var campo = document.createElement('input');
      campo.type = 'hidden';
      campo.name = 'texto-' + caja.getAttribute('data-id');
      campo.value = caja.value;
      campo.setAttribute('data-temporal', '');
      formulario.appendChild(campo);
      puestos.push(campo);
    });
    return puestos;
  }

  var avisoFlotante = null;
  function avisar(texto) {
    if (!avisoFlotante) {
      avisoFlotante = document.createElement('div');
      avisoFlotante.className = 'aviso-flotante';
      avisoFlotante.setAttribute('role', 'status');
      document.body.appendChild(avisoFlotante);
    }
    avisoFlotante.textContent = texto;
    avisoFlotante.classList.add('visible');
    clearTimeout(avisar.temporizador);
    avisar.temporizador = setTimeout(function () {
      avisoFlotante.classList.remove('visible');
    }, 5000);
  }

  function ids(selector) {
    return [].slice.call(document.querySelectorAll(selector)).map(function (e) { return e.id; });
  }

  // Swap in what changed from a freshly rendered copy of the page, keeping
  // the document pane, the sheet list and the sheet itself where they were.
  function reemplazar(nuevo) {
    var documento = document.querySelector('.panel-documento');
    var lista = document.querySelector('.lista-hojas');
    var desplazamiento = documento ? documento.scrollTop : 0;
    var desplazamientoLista = lista ? lista.scrollTop : 0;
    var antes = ids('.fila-entrada');

    ['.panel-documento', '.panel-lateral', '.control-guardar',
     '.barra-comandos .resumen', '.barra-comandos .resumen-avanzado'
    ].forEach(function (selector) {
      var viejo = document.querySelector(selector);
      var fresco = nuevo.querySelector(selector);
      if (viejo && fresco) { viejo.innerHTML = fresco.innerHTML; }
    });

    documento = document.querySelector('.panel-documento');
    lista = document.querySelector('.lista-hojas');
    if (documento) { documento.scrollTop = desplazamiento; }
    if (lista) { lista.scrollTop = desplazamientoLista; }

    // A line just added: show which, without moving the page to it.
    var despues = ids('.fila-entrada');
    despues.filter(function (id) { return antes.indexOf(id) < 0; }).forEach(function (id) {
      var fila = document.getElementById(id);
      if (!fila) { return; }
      fila.classList.add('recien-anadida');
      setTimeout(function () { fila.classList.remove('recien-anadida'); }, 1500);
    });
    pintarPendientes();
  }

  function recargarSinSaltar() {
    return fetch(location.href, { credentials: 'same-origin' })
      .then(function (r) { return r.text(); })
      .then(function (t) { reemplazar(new DOMParser().parseFromString(t, 'text/html')); });
  }

  function enviar(formulario, boton) {
    var puestos = adjuntarEditadas(formulario);
    var datos;
    try { datos = new FormData(formulario, boton || undefined); }
    catch (e) {
      datos = new FormData(formulario);
      if (boton && boton.name) { datos.append(boton.name, boton.value); }
    }
    puestos.forEach(function (campo) { campo.remove(); });

    var accion = formulario.getAttribute('action') || '';
    var botones = [].slice.call(formulario.querySelectorAll('button'));
    botones.forEach(function (b) { b.disabled = true; });
    document.body.classList.add('ocupado');

    return fetch(accion, {
      method: 'POST',
      body: new URLSearchParams(datos),
      credentials: 'same-origin'
    }).then(function (respuesta) {
      return respuesta.text().then(function (texto) {
        if (!respuesta.ok) {
          avisar(texto.trim() || 'No se pudo completar la acción.');
          return;
        }
        var nuevo = new DOMParser().parseFromString(texto, 'text/html');

        // Turning a sheet changes the picture, not the document: fetch the
        // image again, past any cached copy.
        if (/\\/girar$/.test(accion)) {
          var imagen = document.querySelector('.imagen-hoja');
          if (imagen) {
            imagen.src = imagen.getAttribute('src').split('?')[0] + '?v=' + Date.now();
          }
          return;
        }

        // Not the month page: a notice (a refused line, a document that
        // could not be written). Say it, and bring the page up to date.
        if (!nuevo.querySelector('.panel-documento')) {
          var principal = nuevo.querySelector('main');
          avisar(((principal && principal.textContent) || texto).replace(/\\s+/g, ' ').trim());
          return recargarSinSaltar();
        }

        // Every button keeps the sheet that is open. The one exception is
        // correcting the open sheet's own date, which renames its image:
        // then the page is loaded properly rather than half swapped.
        var imagenAhora = document.querySelector('.imagen-hoja');
        var imagenNueva = nuevo.querySelector('.imagen-hoja');
        if (imagenAhora && imagenNueva &&
            imagenAhora.getAttribute('src').split('?')[0] !== imagenNueva.getAttribute('src')) {
          enviando = true;
          location.href = respuesta.url;
          return;
        }
        reemplazar(nuevo);
        // Keep the address in step, without the fragment that used to jump.
        if (respuesta.url) { history.replaceState(null, '', respuesta.url.split('#')[0]); }
        if (/^\\/guardar\\//.test(accion)) { avisar('Guardado. Documento actualizado.'); }
      });
    }).catch(function () {
      avisar('No se pudo conectar con el servidor. Nada se ha perdido: inténtelo de nuevo.');
    }).then(function () {
      botones.forEach(function (b) { if (document.contains(b)) { b.disabled = false; } });
      document.body.classList.remove('ocupado');
    });
  }

  document.addEventListener('submit', function (evento) {
    var formulario = evento.target;
    if ((formulario.getAttribute('method') || '').toLowerCase() !== 'post') { return; }
    if (!window.fetch || !window.DOMParser) {
      // Old browser: post the ordinary way, carrying the edited boxes.
      adjuntarEditadas(formulario);
      enviando = true;
      return;
    }
    evento.preventDefault();
    if (document.body.classList.contains('ocupado')) { return; }
    enviar(formulario, evento.submitter);
  });

  document.addEventListener('keydown', function (evento) {
    if ((evento.ctrlKey || evento.metaKey) && !evento.altKey &&
        (evento.key === 's' || evento.key === 'S')) {
      // Always swallowed, even with nothing to save: the browser's own
      // "save page as" is never what someone pressing Ctrl+S here meant.
      evento.preventDefault();
      var formGuardar = document.getElementById('form-guardar');
      if (!formGuardar || document.body.classList.contains('ocupado')) { return; }
      if (formGuardar.requestSubmit) { formGuardar.requestSubmit(); }
      else if (window.fetch) { enviar(formGuardar, null); }
      else { adjuntarEditadas(formGuardar); enviando = true; formGuardar.submit(); }
    }
  });

  // Leaving by a link, the back button or closing the tab with edits still
  // in the boxes asks first.
  window.addEventListener('beforeunload', function (evento) {
    if (enviando || editadas().length === 0) { return; }
    evento.preventDefault();
    evento.returnValue = '';
  });

  var cabeceraActual = document.querySelector('.cabecera-hoja.actual');
  if (cabeceraActual && !location.hash) {
    cabeceraActual.scrollIntoView({ block: 'start' });
  }
  var hojaLateral = document.querySelector('.hoja-pendiente.seleccionada');
  if (hojaLateral) { hojaLateral.scrollIntoView({ block: 'nearest' }); }

  var AVANZADO_CLAVE = 'memoria-avanzado';
  var botonAvanzado = document.getElementById('alternar-avanzado');
  if (botonAvanzado) {
    var avanzado = leer(AVANZADO_CLAVE) === 'si' ? 'si' : 'no';
    var pintarAvanzado = function () {
      raiz.setAttribute('data-avanzado', avanzado);
      botonAvanzado.setAttribute('aria-pressed', avanzado === 'si' ? 'true' : 'false');
    };
    pintarAvanzado();
    botonAvanzado.addEventListener('click', function () {
      avanzado = (avanzado === 'si') ? 'no' : 'si';
      pintarAvanzado();
      escribir(AVANZADO_CLAVE, avanzado);
    });
  }

  var botonTema = document.getElementById('alternar-tema');
  if (botonTema) {
    botonTema.addEventListener('click', function () {
      tema = (raiz.getAttribute('data-tema') === 'oscuro') ? 'claro' : 'oscuro';
      raiz.setAttribute('data-tema', tema);
      escribir(TEMA_CLAVE, tema);
    });
  }

  var botonLateral = document.getElementById('alternar-lateral');
  if (botonLateral) {
    botonLateral.addEventListener('click', function () {
      lateral = (raiz.getAttribute('data-lateral') === 'cerrado') ? 'abierto' : 'cerrado';
      raiz.setAttribute('data-lateral', lateral);
      document.querySelectorAll('.disposicion').forEach(function (nodo) {
        nodo.setAttribute('data-lateral', lateral);
      });
      botonLateral.setAttribute('aria-expanded', lateral === 'cerrado' ? 'false' : 'true');
      escribir(LATERAL_CLAVE, lateral);
    });
    botonLateral.setAttribute('aria-expanded', lateral === 'cerrado' ? 'false' : 'true');
  }

  // The resize handle itself needs no script; this only remembers, per
  // browser, the width a person last dragged it to.
  var panelImagen = document.querySelector('.panel-imagen');
  if (panelImagen) {
    var anchoGuardado = leer(ANCHO_IMAGEN_CLAVE);
    if (anchoGuardado) { panelImagen.style.width = anchoGuardado; }
    if (window.ResizeObserver) {
      new ResizeObserver(function () {
        escribir(ANCHO_IMAGEN_CLAVE, panelImagen.getBoundingClientRect().width + 'px');
      }).observe(panelImagen);
    }
  }

  // The splitter. Width = distance from the pointer to the layout's right
  // edge, clamped so neither the sheet nor the document can be squeezed
  // out of use. The ResizeObserver above already remembers whatever width
  // this leaves, so there is nothing extra to save here.
  var divisor = document.querySelector('.divisor-imagen');
  var disposicion = document.querySelector('.disposicion');
  if (divisor && panelImagen && disposicion) {
    var ANCHO_MIN = 220;
    var DOCUMENTO_MIN = 320;
    var ANCHO_INICIAL = 480;

    function limitar(ancho) {
      var caja = disposicion.getBoundingClientRect();
      var lateral = document.querySelector('.panel-lateral');
      var ocupado = lateral ? lateral.getBoundingClientRect().width : 0;
      var maximo = Math.min(
        window.innerWidth * 0.85,
        caja.width - ocupado - DOCUMENTO_MIN - divisor.offsetWidth
      );
      return Math.max(ANCHO_MIN, Math.min(maximo, ancho));
    }
    function fijarAncho(ancho) {
      var final = Math.round(limitar(ancho));
      panelImagen.style.width = final + 'px';
      divisor.setAttribute('aria-valuenow', String(final));
    }

    divisor.addEventListener('pointerdown', function (evento) {
      if (evento.button !== 0) { return; }
      evento.preventDefault();
      divisor.setPointerCapture(evento.pointerId);
      divisor.classList.add('arrastrando');
      document.body.classList.add('redimensionando');
    });
    divisor.addEventListener('pointermove', function (evento) {
      if (!divisor.hasPointerCapture(evento.pointerId)) { return; }
      var derecha = disposicion.getBoundingClientRect().right;
      fijarAncho(derecha - evento.clientX - divisor.offsetWidth / 2);
    });
    function soltar(evento) {
      if (divisor.hasPointerCapture(evento.pointerId)) {
        divisor.releasePointerCapture(evento.pointerId);
      }
      divisor.classList.remove('arrastrando');
      document.body.classList.remove('redimensionando');
    }
    divisor.addEventListener('pointerup', soltar);
    divisor.addEventListener('pointercancel', soltar);

    // Double-click puts it back where it started.
    divisor.addEventListener('dblclick', function () { fijarAncho(ANCHO_INICIAL); });

    // Arrow keys for anyone not dragging. Left widens the sheet, because the
    // splitter moves left.
    divisor.addEventListener('keydown', function (evento) {
      var paso = evento.shiftKey ? 96 : 32;
      var actual = panelImagen.getBoundingClientRect().width;
      if (evento.key === 'ArrowLeft') { fijarAncho(actual + paso); evento.preventDefault(); }
      else if (evento.key === 'ArrowRight') { fijarAncho(actual - paso); evento.preventDefault(); }
      else if (evento.key === 'Home') { fijarAncho(ANCHO_MIN); evento.preventDefault(); }
      else if (evento.key === 'End') { fijarAncho(99999); evento.preventDefault(); }
    });

    // A width saved on a bigger screen can be too big for this one.
    window.addEventListener('resize', function () {
      fijarAncho(panelImagen.getBoundingClientRect().width);
    });
    fijarAncho(panelImagen.getBoundingClientRect().width);
  }

  // Layer two of the zoom: without this, the link still opens the
  // full-resolution scan on its own page, which is layer one.
  //
  // It used to be a single class toggle -- fit the panel, or natural size,
  // nothing between. Handwriting is read at whatever magnification the hand
  // that wrote it needs, so this is a proper zoom: stepped buttons, the
  // wheel, double-click, and dragging to pan once the sheet is bigger than
  // the panel.
  //
  // A function, run again whenever a new sheet is swapped into the panel
  // without reloading the page. Each run first drops everything the last
  // one hung on the document -- listeners through an AbortController, the
  // resize observer by hand -- so moving through sheets does not pile up
  // handlers for panels that are gone.
  var visorControl = null;
  var observadorVisor = null;

  function iniciarVisor() {
  if (visorControl) { visorControl.abort(); }
  if (observadorVisor) { observadorVisor.disconnect(); observadorVisor = null; }
  visorControl = window.AbortController ? new AbortController() : null;
  function escuchar(objetivo, tipo, funcion, extra) {
    var opciones = extra ? Object.assign({}, extra) : {};
    if (visorControl) { opciones.signal = visorControl.signal; }
    objetivo.addEventListener(tipo, funcion, opciones);
  }

  var enlaceImagen = document.querySelector('.enlace-imagen');
  var imagenHoja = document.querySelector('.imagen-hoja');
  var controlesZoom = document.getElementById('zoom-hoja');
  // The viewer scrolls; the panel around it holds the toolbar still.
  var visorHoja = document.querySelector('.visor-hoja');

  if (enlaceImagen && imagenHoja && visorHoja) {
    var PASOS = [0.25, 0.5, 0.75, 1, 1.5, 2, 3, 4, 6, 8];
    // 0 is "fit the panel", which is not a fixed number: it depends on the
    // panel's width, so it cannot live in PASOS.
    var escala = 0;
    var botonMenos = document.getElementById('zoom-menos');
    var botonMas = document.getElementById('zoom-mas');
    var etiquetaNivel = document.getElementById('nivel-zoom');

    if (controlesZoom) { controlesZoom.hidden = false; }

    // "Ajustar" shows the whole sheet: the largest size at which both its
    // width and its height fit the viewer. It used to fit the width only,
    // so a portrait sheet in a wide panel ran off the bottom.
    function escalaAjuste() {
      if (!imagenHoja.naturalWidth || !imagenHoja.naturalHeight) { return 1; }
      return Math.min(visorHoja.clientWidth / imagenHoja.naturalWidth,
                      visorHoja.clientHeight / imagenHoja.naturalHeight);
    }

    function aplicar() {
      var efectiva = escala || escalaAjuste();
      if (escala === 0) {
        imagenHoja.style.width = Math.floor(imagenHoja.naturalWidth * efectiva) + 'px';
        imagenHoja.style.maxWidth = 'none';
      } else {
        imagenHoja.style.width = (imagenHoja.naturalWidth * escala) + 'px';
        imagenHoja.style.maxWidth = 'none';
      }
      var desplazable = imagenHoja.getBoundingClientRect().width >
                        visorHoja.clientWidth + 1;
      imagenHoja.classList.toggle('desplazable', desplazable);
      if (etiquetaNivel) {
        etiquetaNivel.textContent = escala === 0
          ? 'Ajustar' : Math.round(efectiva * 100) + '%';
      }
      if (botonMenos) { botonMenos.disabled = escala !== 0 && escala <= PASOS[0]; }
      if (botonMas) { botonMas.disabled = escala >= PASOS[PASOS.length - 1]; }
    }

    // Zoom about a point: the pixel under the cursor (or the middle of the
    // panel) has to stay under it, or every step throws away the place being
    // read.
    function fijar(nueva, puntoX, puntoY) {
      var antes = escala || escalaAjuste();
      nueva = Math.max(PASOS[0], Math.min(PASOS[PASOS.length - 1], nueva));
      var caja = visorHoja.getBoundingClientRect();
      var x = (puntoX === undefined) ? caja.width / 2 : puntoX - caja.left;
      var y = (puntoY === undefined) ? caja.height / 2 : puntoY - caja.top;
      var haciaX = (visorHoja.scrollLeft + x) / antes;
      var haciaY = (visorHoja.scrollTop + y) / antes;
      escala = nueva;
      aplicar();
      visorHoja.scrollLeft = haciaX * nueva - x;
      visorHoja.scrollTop = haciaY * nueva - y;
    }

    function paso(direccion, puntoX, puntoY) {
      var actual = escala || escalaAjuste();
      var siguiente = null;
      if (direccion > 0) {
        for (var i = 0; i < PASOS.length; i++) {
          if (PASOS[i] > actual + 0.001) { siguiente = PASOS[i]; break; }
        }
        if (siguiente === null) { return; }
      } else {
        for (var j = PASOS.length - 1; j >= 0; j--) {
          if (PASOS[j] < actual - 0.001) { siguiente = PASOS[j]; break; }
        }
        // Below the smallest step there is only "fit", which is where the
        // panel started and the one state that always shows the whole sheet.
        if (siguiente === null) { escala = 0; aplicar(); return; }
      }
      fijar(siguiente, puntoX, puntoY);
    }

    function ajustar() { escala = 0; aplicar(); visorHoja.scrollTop = 0; }

    if (botonMas) {
      escuchar(botonMas, 'click', function () { paso(1); });
    }
    if (botonMenos) {
      escuchar(botonMenos, 'click', function () { paso(-1); });
    }
    if (etiquetaNivel) {
      escuchar(etiquetaNivel, 'click', ajustar);
    }

    // A click still zooms in, the way it always did; a double-click goes
    // back to fitting, so there is always one gesture that shows the whole
    // sheet again.
    escuchar(enlaceImagen, 'click', function (evento) {
      evento.preventDefault();
      if (arrastrado) { arrastrado = false; return; }
      paso(1, evento.clientX, evento.clientY);
    });
    escuchar(enlaceImagen, 'dblclick', function (evento) {
      evento.preventDefault();
      ajustar();
    });

    // The wheel zooms without a modifier, because the panel is the image:
    // there is nothing else in it to scroll past. Shift or a horizontal
    // wheel is left alone so a trackpad can still pan.
    escuchar(visorHoja, 'wheel', function (evento) {
      if (evento.shiftKey || Math.abs(evento.deltaX) > Math.abs(evento.deltaY)) {
        return;
      }
      evento.preventDefault();
      paso(evento.deltaY < 0 ? 1 : -1, evento.clientX, evento.clientY);
    }, { passive: false });

    // Drag to pan, once there is more sheet than panel.
    var arrastrando = false;
    var arrastrado = false;
    var desdeX = 0, desdeY = 0, scrollX = 0, scrollY = 0;

    escuchar(imagenHoja, 'mousedown', function (evento) {
      if (evento.button !== 0) { return; }
      if (!imagenHoja.classList.contains('desplazable') &&
          visorHoja.scrollHeight <= visorHoja.clientHeight) { return; }
      arrastrando = true;
      arrastrado = false;
      desdeX = evento.clientX;
      desdeY = evento.clientY;
      scrollX = visorHoja.scrollLeft;
      scrollY = visorHoja.scrollTop;
      imagenHoja.classList.add('agarrando');
      visorHoja.classList.add('arrastrando');
      evento.preventDefault();
    });

    escuchar(document, 'mousemove', function (evento) {
      if (!arrastrando) { return; }
      var dx = evento.clientX - desdeX;
      var dy = evento.clientY - desdeY;
      // A few pixels of wobble is a click, not a drag; without this every
      // click that moved slightly would be swallowed as a pan.
      if (Math.abs(dx) > 3 || Math.abs(dy) > 3) { arrastrado = true; }
      visorHoja.scrollLeft = scrollX - dx;
      visorHoja.scrollTop = scrollY - dy;
    });

    escuchar(document, 'mouseup', function () {
      if (!arrastrando) { return; }
      arrastrando = false;
      imagenHoja.classList.remove('agarrando');
      visorHoja.classList.remove('arrastrando');
    });

    // Keyboard, for whoever is not using a mouse.
    escuchar(document, 'keydown', function (evento) {
      if (evento.target && /^(INPUT|TEXTAREA)$/.test(evento.target.tagName)) {
        return;
      }
      if (evento.key === '+' || evento.key === '=') { paso(1); }
      else if (evento.key === '-') { paso(-1); }
      else if (evento.key === '0') { ajustar(); }
    });

    // Every sheet opens fitted. The zoom level used to be remembered, so
    // zooming into one sheet opened the next one zoomed in too.
    // naturalWidth is 0 until the image has loaded, and every figure here
    // depends on it.
    // Every load, not only the first: a turn swaps the picture in place and
    // its width and height change places.
    escuchar(imagenHoja, 'load', aplicar);
    if (imagenHoja.complete && imagenHoja.naturalWidth) { aplicar(); }
    // Re-fitting matters only in the fit state, where the width is the
    // panel's; a fixed zoom is unaffected by the panel being dragged.
    if (window.ResizeObserver) {
      observadorVisor = new ResizeObserver(function () { if (escala === 0) { aplicar(); } });
      observadorVisor.observe(visorHoja);
    }
  }
  }
  iniciarVisor();

  // Moving between sheets without reloading. Every link within this month
  // -- a sheet heading, the sheet list, the arrows, a candidate page, the
  // list switch -- used to load a whole new page. Now the same page is
  // fetched and the document, the list, the counts and the sheet panel are
  // swapped in; the address changes as before, and back and forward work.
  // A link to another month, or any failure, still loads the page normally.
  function navegar(href, empujar, quieto) {
    if (document.body.classList.contains('ocupado')) { return; }
    var destino = new URL(href, location.href);
    // Unsaved boxes must survive the swap exactly as they are.
    var pendientes = editadas().map(function (caja) {
      return [caja.getAttribute('data-id'), caja.value];
    });
    document.body.classList.add('ocupado');
    fetch(destino.pathname + destino.search, { credentials: 'same-origin' })
      .then(function (respuesta) {
        if (!respuesta.ok) { throw new Error(String(respuesta.status)); }
        return respuesta.text();
      })
      .then(function (texto) {
        var nuevo = new DOMParser().parseFromString(texto, 'text/html');
        if (!nuevo.querySelector('.panel-documento')) { throw new Error('no page'); }
        reemplazar(nuevo);
        var panel = document.querySelector('.panel-imagen');
        var panelNuevo = nuevo.querySelector('.panel-imagen');
        if (panel && panelNuevo) {
          panel.innerHTML = panelNuevo.innerHTML;
          iniciarVisor();
        }
        pendientes.forEach(function (par) {
          var caja = document.querySelector('.texto-entrada[data-id="' + par[0] + '"]');
          if (caja) { caja.value = par[1]; }
        });
        pintarPendientes();
        if (empujar) { history.pushState(null, '', destino.href); }
        if (destino.hash && !quieto) {
          var objetivo = document.getElementById(decodeURIComponent(destino.hash.slice(1)));
          if (objetivo) { objetivo.scrollIntoView({ block: 'start' }); }
        }
        var enLista = document.querySelector('.hoja-pendiente.seleccionada');
        if (enLista) { enLista.scrollIntoView({ block: 'nearest' }); }
      })
      .catch(function () { location.href = destino.href; })
      .then(function () { document.body.classList.remove('ocupado'); });
  }

  document.addEventListener('click', function (evento) {
    if (evento.defaultPrevented || evento.button !== 0 ||
        evento.metaKey || evento.ctrlKey || evento.shiftKey || evento.altKey) { return; }
    var enlace = evento.target.closest ? evento.target.closest('a[href]') : null;
    if (!enlace || enlace.target || enlace.classList.contains('enlace-imagen')) { return; }
    if (!window.fetch || !window.DOMParser) { return; }
    var destino = new URL(enlace.getAttribute('href'), location.href);
    if (destino.origin !== location.origin || destino.pathname !== location.pathname) { return; }
    evento.preventDefault();
    // A link clicked inside the document is already where the eye is; one
    // from the list or the arrows brings its sheet into view. A sheet
    // heading is the exception: the sheet it opens goes to the top of the
    // document, as one opened from the list does.
    var quieto = !!enlace.closest('.panel-documento') &&
                 !enlace.classList.contains('cabecera-hoja');
    navegar(destino.href, true, quieto);
  });

  window.addEventListener('popstate', function () { navegar(location.href, false, false); });

  // Where the browser cannot size a box to its text (field-sizing), do it
  // here: on load, as it is typed into, and whenever the document is swapped.
  if (!(window.CSS && CSS.supports && CSS.supports('field-sizing', 'content'))) {
    var ajustar = function (caja) {
      caja.style.height = 'auto';
      caja.style.height = (caja.scrollHeight + 2) + 'px';
    };
    var ajustarTodas = function () {
      [].forEach.call(document.querySelectorAll('.texto-entrada'), ajustar);
    };
    document.addEventListener('input', function (evento) {
      if (evento.target.classList && evento.target.classList.contains('texto-entrada')) {
        ajustar(evento.target);
      }
    });
    new MutationObserver(ajustarTodas).observe(
      document.querySelector('.panel-documento') || document.body, { childList: true });
    ajustarTodas();
  }
})();
"""


def maintenance_page() -> str:
    """What the colleague sees while the panel is being worked on.

    Self-contained -- no script, no links into the dashboard -- and it
    reloads itself, so when the work is finished the dashboard comes back
    without anybody doing anything.
    """
    return """<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="30">
<title>Panel en mantenimiento</title>
<style>
:root { color-scheme: light dark; --page: #f3f2f1; --text: #1b1b1b; --muted: #5b5b5b; }
@media (prefers-color-scheme: dark) { :root { --page: #1f1f1f; --text: #ededed; --muted: #a6a6a6; } }
body { margin: 0; min-height: 100vh; display: flex; align-items: center; justify-content: center;
       background: var(--page); color: var(--text); font-family: "Segoe UI", system-ui, sans-serif; }
main { max-width: 28rem; padding: 24px; text-align: center; }
h1 { font-size: 22px; margin: 0 0 12px; }
p { margin: 0 0 8px; color: var(--muted); }
</style>
</head>
<body>
<main>
<h1>Panel en mantenimiento</h1>
<p>Se están haciendo cambios en el panel. Vuelva a intentarlo en unos minutos.</p>
<p>Esta página se recargará sola cuando el panel vuelva.</p>
</main>
</body>
</html>
"""


def with_maintenance_strip(document: str) -> str:
    """The author's page, with a reminder that only they can see it."""
    aviso = ('<div class="aviso-mantenimiento" role="status">Modo mantenimiento activo: '
             'solo usted ve el panel. Desactívelo con deploy/maintenance.sh off.</div>')
    return document.replace("<body>", "<body>\n" + aviso, 1)


def page(
    title: str, body: str, *, advanced: bool = False, active: str = "seguridad",
    resumen: str = "", acciones: str = "", year_month: tuple[str, str] | None = None,
) -> str:
    """Wrap a body fragment in the command bar and the document shell.

    *advanced* only decides whether the caller chose to show the author's
    numbers upstream (in the body it was given); this function does not
    branch on it itself, it just carries the flag through in case a caller
    wants it reflected in a class.
    """
    # The switch is only rendered for an address the server already decided
    # may see the numbers; the numbers themselves are still omitted from the
    # markup for everyone else, so this is a display control, not the gate.
    interruptor = _INTERRUPTOR_AVANZADO if advanced else ""
    esc_title = html.escape(str(title))
    # Real hrefs, not "?seccion=...": nothing has ever read a seccion query
    # parameter, so both tabs used to reload the page unchanged. Seguridad
    # points at "/", which redirects to the newest month with entries -- the
    # one piece of routing that already knows where the work is, so page()
    # does not need to be told the year and month to link back to.
    # On a month's page each tab opens that same month in its section, so
    # switching between the two keeps the month being worked on.
    if year_month:
        esc_ym = "/".join(html.escape(str(part)) for part in year_month)
        seguridad_href = f"{SECTION_PATHS['seguridad']}/{esc_ym}"
        mantenimiento_href = f"{SECTION_PATHS['mantenimiento']}/{esc_ym}"
    else:
        seguridad_href, mantenimiento_href = "/", "/mantenimiento"
    seguridad_clase = "activo" if active == "seguridad" else ""
    mantenimiento_clase = "activo" if active == "mantenimiento" else ""
    # The script corrects this before first paint from what the browser
    # remembers; "true" is the server's only honest default.
    lateral_expandido = "true"
    seguridad_seleccion = "true" if active == "seguridad" else "false"
    mantenimiento_seleccion = "true" if active == "mantenimiento" else "false"
    return f"""<!doctype html>
<html lang="es" data-tema="claro" data-lateral="abierto">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc_title}</title>
<link rel="icon" href="data:,">
<script>{_PRIMER_PINTADO}</script>
<style>{STYLESHEET}</style>
</head>
<body>
<header class="barra-comandos">
  <button id="alternar-lateral" class="boton-icono" type="button"
          aria-expanded="{lateral_expandido}"
          aria-label="Mostrar u ocultar el panel lateral"
          title="Mostrar u ocultar el panel lateral">{_ICONO_LATERAL}</button>
  <nav class="secciones" role="tablist">
    <a href="{seguridad_href}" class="{seguridad_clase}" role="tab"
       aria-selected="{seguridad_seleccion}">Seguridad</a>
    <a href="{mantenimiento_href}" class="{mantenimiento_clase}" role="tab"
       aria-selected="{mantenimiento_seleccion}">Mantenimiento</a>
  </nav>
  {acciones}
  <span style="flex:1"></span>
  {resumen}
  {interruptor}
  <button id="alternar-tema" class="boton-icono" type="button"
          aria-label="Cambiar de tema"
          title="Cambiar entre tema claro y oscuro">{_ICONO_TEMA}</button>
</header>
<main>
{body}
</main>
<script>{_SCRIPT}</script>
</body>
</html>"""


# Where each section's month view lives. Seguridad kept /mes/ so every
# bookmark and emailed link from before the Mantenimiento view still works.
SECTION_PATHS = {"seguridad": "/mes", "mantenimiento": "/mantenimiento"}


def _view_fields(selected_hoja: str | None, showing_all: bool,
                 section: str = "seguridad", tag_filter: str = "") -> str:
    """Hidden fields carrying what the person is looking at through a POST,
    and which tag is being shown.

    Without them every write redirected to the bare month page, closing the
    open sheet: press Guardar línea and the scan you were reading from was
    gone. dashboard._back_to_month re-validates both before using them.
    """
    campos = ""
    if selected_hoja:
        campos += (f'<input type="hidden" name="hoja" '
                   f'value="{html.escape(str(selected_hoja))}">')
    if not showing_all:
        campos += '<input type="hidden" name="hojas" value="pendientes">'
    if section != "seguridad":
        campos += f'<input type="hidden" name="seccion" value="{html.escape(section)}">'
    if tag_filter in SLUGS:
        campos += f'<input type="hidden" name="bloque" value="{tag_filter}">'
    return campos


def _entry_row(
    entry: dict, esc_token: str, esc_year: str, esc_month: str, selected_hoja: str | None,
    vista: str = "", asignar: str = "", etiqueta: str = "", tag_slug: str = "",
) -> str:
    """One entry as a row: the flag mark, the editable text, the two actions,
    and -- when this entry has a source page -- the link to it.

    Two plain forms, not one: editing a line and confirming or deleting it
    are different routes (/entrada/{id} takes new text, /entradas/{id} takes
    an accion), and a browser can only give one <form> one action. Neither
    depends on the page's script -- a contenteditable div used to hold the
    text, which no plain form submission carries, so an edit had nowhere to
    go without JavaScript that was never wired up to send it anywhere. A
    <textarea> inside a real form works with or without it.

    The sheet link is a plain anchor to this same page with ?hoja= set and a
    fragment naming this row's own id, so opening the image and coming back
    lands on the line he was reading, not the top of the document -- also no
    script required, just a second page load.
    """
    entry_id = html.escape(str(entry.get("id", "")))
    text = html.escape(str(entry.get("text", "")))
    flagged = bool(entry.get("flagged"))
    marca = (
        f'<span class="marca-dudosa" title="Lectura dudosa, sin confirmar">{_ICONO_MARCA}</span>'
        if flagged else '<span class="marca-dudosa resuelta" aria-hidden="true"></span>'
    )

    # A line already marked has Correcto to clear it; any other can be marked
    # for the next person to read against the paper.
    revisar = "" if flagged else (
        '<button type="submit" name="accion" value="revisar" class="boton-revisar" '
        'aria-label="Marcar para revisar" title="Marcar para revisar">'
        f'{_ICONO_MARCA}<span class="solo-lector">Marcar para revisar</span></button>'
    )

    review_ref = entry.get("review_ref") or ""
    fila_clase = "fila-entrada"
    # No per-line sheet link any more: the lines are grouped under a heading
    # that names the sheet and opens it, so repeating it on every row was the
    # same text over and over down the page.
    enlace_hoja = ""
    if review_ref:
        archivo = image_name(review_ref)
        if selected_hoja and archivo == selected_hoja:
            fila_clase += " hoja-actual"

    if asignar:
        fila_clase += " sin-hoja"
    datos = ""
    if tag_slug in SLUGS:
        fila_clase += " con-etiqueta"
        datos = f' data-etiqueta="{tag_slug}"'
    return f"""<div class="{fila_clase}" id="entrada-{entry_id}"{datos}>
  {marca}
  <form class="forma-texto" method="post" action="/entrada/{entry_id}">
    <input type="hidden" name="csrf" value="{esc_token}">{vista}
    <textarea class="texto-entrada" name="texto" data-id="{entry_id}" rows="3">{text}</textarea>
    <button type="submit" class="boton-icono">Guardar línea</button>
  </form>
  {enlace_hoja}
  <form class="acciones-entrada" method="post" action="/entradas/{entry_id}">
    <input type="hidden" name="csrf" value="{esc_token}">{vista}
    <input type="hidden" name="id" value="{entry_id}">
    <button type="submit" name="accion" value="confirmar" class="boton-correcto">{_ICONO_CORRECTO}Correcto</button>
    {revisar}
    <button type="submit" name="accion" value="eliminar" class="boton-eliminar" aria-label="Eliminar" title="Eliminar">{_ICONO_PAPELERA}<span class="solo-lector">Eliminar</span></button>
  </form>
  {etiqueta}
  {asignar}
</div>"""


def _add_line(esc_token: str, vista: str, *, after_id=None, before_id=None) -> str:
    """A collapsed "Añadir línea" that opens into a box and a button.

    A native <details>, so it opens with no script; the form posts to
    /entrada/nueva like everything else that writes. after_id puts the line
    below a row, before_id above the first row of a sheet -- the only place
    "below the previous line" would put it under the wrong sheet.
    """
    if before_id is not None:
        campo = f'<input type="hidden" name="before_id" value="{html.escape(str(before_id))}">'
        texto = "Añadir línea al principio de esta hoja"
    else:
        campo = f'<input type="hidden" name="after_id" value="{html.escape(str(after_id))}">'
        texto = "Añadir línea debajo"
    return (
        '<details class="anadir-linea">'
        f'<summary title="{texto}"><span class="mas" aria-hidden="true">+</span>'
        f'<span class="texto-anadir">{texto}</span></summary>'
        '<form class="forma-anadir" method="post" action="/entrada/nueva">'
        f'<input type="hidden" name="csrf" value="{esc_token}">{vista}{campo}'
        '<textarea class="texto-nuevo" name="texto" rows="2" '
        'placeholder="Escriba la línea que falta"></textarea>'
        '<button type="submit" class="boton-icono">Añadir</button>'
        '</form></details>'
    )


def _tag_chip(entry: dict, esc_token: str, vista: str) -> str:
    """The line's subheading, which opens into the four it can be moved to.

    A native <details> with a plain form, like "Añadir línea": the choice
    is a submit button, so it works whether or not the page's script ran.
    """
    block = entry.get("block", "")
    actual = slug_of(block)
    if not actual:
        return ""
    entry_id = html.escape(str(entry.get("id", "")))
    opciones = []
    for slug, nombre in SLUGS.items():
        pulsado = ' aria-pressed="true"' if slug == actual else ""
        opciones.append(
            f'<button type="submit" name="etiqueta" value="{slug}" '
            f'class="opcion-etiqueta etiqueta-{slug}"{pulsado}>'
            f'{html.escape(SHORT_NAMES[nombre])}</button>'
        )
    return (
        '<details class="etiqueta-linea">'
        f'<summary class="etiqueta etiqueta-{actual}" title="{html.escape(block)}">'
        f'{html.escape(SHORT_NAMES[block])}</summary>'
        f'<form class="menu-etiquetas" method="post" action="/entrada/{entry_id}/bloque">'
        f'<input type="hidden" name="csrf" value="{esc_token}">{vista}'
        f'{"".join(opciones)}</form></details>'
    )


def _filter_bar(counts: dict, tag_filter: str, href: str, keep: str = "") -> str:
    """Todas and the four subheadings, each with the month's count.

    Plain links to this same page: the count is for the whole month whatever
    is being shown, so the bar also says how the memoria will divide up.
    """
    def enlace(nombre: str, cuenta: int, slug: str) -> str:
        texto = f'{html.escape(nombre)} <span class="cuenta">{cuenta}</span>'
        clase = f" etiqueta-{slug}" if slug else ""
        if slug == tag_filter:
            return f'<span class="actual{clase}" aria-current="true">{texto}</span>'
        # keep: the open sheet and the shortlist, which a filter must not close.
        destino = (f"{href}?bloque={slug}{keep}" if slug
                   else (f"{href}?{keep[1:]}" if keep else href))
        return f'<a class="{clase.strip()}" href="{destino}">{texto}</a>'

    total = sum(counts.get(block, 0) for block in SLUGS.values())
    partes = [enlace("Todas", total, "")]
    partes += [enlace(SHORT_NAMES[block], counts.get(block, 0), slug)
               for slug, block in SLUGS.items()]
    return (f'<nav class="filtro-etiquetas" aria-label="Mostrar un apartado">'
            f'{"".join(partes)}</nav>')


def _moved_notice(moved_to: str) -> str:
    """"Línea movida a Otros.": where a line went when its tag left the view."""
    if moved_to not in SLUGS:
        return ""
    return (f'<p class="aviso-movida" role="status">Línea movida a '
            f'<strong>{html.escape(SHORT_NAMES[SLUGS[moved_to]])}</strong>.</p>\n')


def _month_list(months: list, year: str, month: str, base: str = "/mes") -> str:
    """Every month that has entries, grouped by year, newest first.

    The only way to reach a month used to be "/", which always goes to the
    newest one; an older month could be opened only by typing its URL.
    Built from the data, so a month appears because something was filed in
    it, for any year. Plain links: nothing here needs a script.
    """
    if len(months) < 2:
        return ""
    por_anio: dict[str, list[str]] = {}
    for y, m in months:
        por_anio.setdefault(str(y), []).append(str(m))
    grupos = []
    for y in sorted(por_anio, key=lambda v: int(v) if v.isdigit() else 0, reverse=True):
        enlaces = []
        for m in reversed(por_anio[y]):
            nombre = html.escape(m.capitalize())
            if y == str(year) and m == str(month):
                enlaces.append(f'<span class="mes-actual" aria-current="page">{nombre}</span>')
            else:
                enlaces.append(
                    f'<a href="{base}/{html.escape(y)}/{html.escape(m)}">{nombre}</a>'
                )
        grupos.append(
            f'<div class="anio-meses"><span class="anio">{html.escape(y)}</span>'
            f'<span class="meses">{"".join(enlaces)}</span></div>'
        )
    return f'<nav class="selector-meses" aria-label="Meses">{"".join(grupos)}</nav>'


def _page_label(review_ref: str) -> str:
    """'página 41 (11-09-2026)', or 'página 13 (sin fecha)'.

    "sin fecha", not "fecha ilegible": a sheet rebuilt from the archive was
    never read at all, so nobody knows whether its date is legible.
    """
    match = _REF.match(plain_ref(review_ref))
    if not match:
        return plain_ref(review_ref)
    sheet, page = match.group(1), match.group(2)
    fecha = sheet if re.fullmatch(r"\d{2}-\d{2}-\d{4}", sheet) else "sin fecha"
    return f"página {page} ({fecha})"


def _unconfirmed_heading(
    candidatos: list, esc_year: str, esc_month: str, first_id, selected_hoja,
    base: str = "/mes", extra: str = "",
) -> str:
    """The band over lines whose page was never recorded.

    Every line was read off a page; what was lost is which one. The pages
    it can be from are named, each opening in the sheet panel, so the
    person can look and choose.
    """
    if not candidatos:
        return ('<div class="cabecera-hoja sin-referencia">'
                "<span>Página no registrada</span></div>")
    enlaces = []
    for ref in candidatos:
        archivo = image_name(ref)
        clase = "candidata actual" if selected_hoja == archivo else "candidata"
        enlaces.append(
            f'<a class="{clase}" href="{base}/{esc_year}/{esc_month}'
            f'?hoja={html.escape(archivo)}{extra}#entrada-{html.escape(str(first_id))}">'
            f'{html.escape(_page_label(ref))}</a>'
        )
    return (
        '<div class="cabecera-hoja sin-referencia" title="La página de estas '
        'líneas no se guardó al leerlas. Abra las candidatas y elija la suya.">'
        '<span>Página sin confirmar:</span> '
        + ' <span class="o">o</span> '.join(enlaces)
        + "</div>"
    )


def _assign_sheet(entry_id, candidatos: list, esc_token: str, vista: str) -> str:
    """One button per candidate page, under a line with no recorded page."""
    if not candidatos:
        return ""
    esc_id = html.escape(str(entry_id))
    botones = "".join(
        f'<form method="post" action="/entrada/{esc_id}/hoja">'
        f'<input type="hidden" name="csrf" value="{esc_token}">{vista}'
        f'<input type="hidden" name="hoja_elegida" value="{html.escape(image_name(ref))}">'
        f'<button type="submit" class="boton-asignar">'
        f'Es la {html.escape(_page_label(ref))}</button></form>'
        for ref in candidatos
    )
    return (f'<div class="asignar-hoja"><span class="pregunta">¿De qué página es?</span>'
            f'{botones}</div>')


def _sheet_short_label(review_ref: str) -> str:
    """'01-09-2026 · p2', or 'sin fecha · p27' for a sheet named after its scan."""
    match = _REF.match(plain_ref(review_ref))
    if not match:
        return plain_ref(review_ref)
    sheet, page = match.group(1), match.group(2)
    fecha = sheet if re.fullmatch(r"\d{2}-\d{2}-\d{4}", sheet) else "sin fecha"
    return f"{fecha} \u00b7 p{page}"


def _month_bounds(year: str, month: str) -> tuple[str, str]:
    """First and last day of the folder's month, as the date input wants them."""
    import calendar

    from nettune.report.month_folders import MONTH_FOLDERS

    if month not in MONTH_FOLDERS or not str(year).isdigit():
        return "", ""
    number = MONTH_FOLDERS.index(month) + 1
    last = calendar.monthrange(int(year), number)[1]
    return f"{year}-{number:02d}-01", f"{year}-{number:02d}-{last:02d}"


def _date_control(review_ref: str, year: str, month: str, esc_token: str, vista: str,
                  suggestions: list | None) -> str:
    """Setting a sheet's date, under its heading.

    Three states. A date that does not fit the scan -- *suggestions* is a
    list, possibly empty -- is questioned openly, with the neighbours' dates
    as one-click answers. A sheet with no date asks for one. Any other sheet
    keeps the control folded away, for the rare date that fits and is still
    wrong.
    """
    archivo = html.escape(image_name(review_ref))
    accion = f"/hoja/{archivo}/fecha"
    oculto = f'<input type="hidden" name="csrf" value="{esc_token}">{vista}'
    minimo, maximo = _month_bounds(year, month)
    fecha_leida = plain_ref(review_ref).split(" ")[0]
    fechada = bool(re.fullmatch(r"\d{2}-\d{2}-\d{4}", fecha_leida))
    valor = ""
    if fechada:
        d, m, a = fecha_leida.split("-")
        valor = f"{a}-{m}-{d}"
    otra = (
        f'<form class="forma-fecha" method="post" action="{accion}">{oculto}'
        f'<input type="date" name="fecha" required min="{minimo}" max="{maximo}"'
        f' value="{valor}" aria-label="Fecha de la hoja">'
        '<button type="submit" class="boton-icono">Guardar fecha</button></form>'
    )
    if suggestions is not None:
        sugeridas = "".join(
            f'<form method="post" action="{accion}">{oculto}'
            f'<input type="hidden" name="fecha" value="{html.escape(f)}">'
            f'<button type="submit" class="boton-asignar">Es el {html.escape(f)}</button></form>'
            for f in suggestions
        )
        confirmar = (
            f'<form method="post" action="{accion}">{oculto}'
            '<input type="hidden" name="confirmar" value="1">'
            '<button type="submit" class="boton-icono">La fecha leída es correcta</button></form>'
        )
        return (
            '<div class="fecha-hoja dudosa">'
            f'<span class="pregunta">¿Fecha correcta? Se leyó {html.escape(fecha_leida)},'
            ' que no encaja con las hojas de al lado.</span>'
            f'<div class="opciones-fecha">{sugeridas}{otra}{confirmar}</div></div>'
        )
    if not fechada:
        return (
            '<div class="fecha-hoja sin-fecha">'
            '<span class="pregunta">Hoja sin fecha. Mírela y escriba la suya:</span>'
            f'<div class="opciones-fecha">{otra}</div></div>'
        )
    return (
        '<details class="fecha-hoja cambiar"><summary>Cambiar la fecha de esta hoja</summary>'
        f'<div class="opciones-fecha">{otra}</div></details>'
    )


def _empty_sheet(review_ref: str, esc_token: str, vista: str,
                 confirmed: bool = False) -> str:
    """The body of a sheet no line points at: say so, and let lines be added.

    Or, once someone has looked, let them say there is nothing to add: until
    then the sheet counts as still to check, and the final document waits.
    """
    archivo = html.escape(image_name(review_ref))
    if confirmed:
        aviso = '<p>Revisada: no hay nada que añadir de esta hoja.</p>'
    else:
        aviso = (
            '<p>La lectura no encontró ninguna línea en esta hoja. Ábrala y añada '
            'lo que haya escrito, o confirme que no hay nada.</p>'
            f'<form method="post" action="/hoja/{archivo}/vacia">'
            f'<input type="hidden" name="csrf" value="{esc_token}">{vista}'
            '<button type="submit" class="boton-icono">Revisada: no hay nada que añadir'
            '</button></form>'
        )
    return (
        '<div class="hoja-vacia">'
        f'{aviso}'
        f'<form class="forma-anadir" method="post" action="/hoja/{archivo}/linea">'
        f'<input type="hidden" name="csrf" value="{esc_token}">{vista}'
        '<textarea class="texto-nuevo" name="texto" rows="2" '
        'placeholder="Escriba una línea de esta hoja"></textarea>'
        '<button type="submit" class="boton-icono">Añadir línea</button>'
        '</form></div>'
    )


def _sheet_anchor(archivo: str) -> str:
    """The id a sheet's first heading carries, and the fragment that finds it."""
    return "hoja-" + html.escape(archivo)


def _sheet_heading(
    review_ref: str, esc_year: str, esc_month: str, selected_hoja: str | None,
    with_id: bool = True, base: str = "/mes", extra: str = "",
) -> str:
    """The band that opens a sheet's run of lines in the document pane.

    Clicking it opens that sheet in the image panel, so the heading is also
    the way into the page the lines under it were read from.
    """
    if not review_ref:
        return ('<div class="cabecera-hoja sin-referencia" title="Leída antes de '
                'que el sistema guardara la hoja de cada línea; está en el orden '
                'del escaneo, junto a las líneas que la rodeaban.">'
                "<span>Hoja sin identificar</span></div>")
    archivo = image_name(review_ref)
    esc_archivo = html.escape(archivo)
    clase = "cabecera-hoja"
    if selected_hoja and archivo == selected_hoja:
        clase += " actual"
    # Only the first heading for a sheet takes the id: a sheet with lines in
    # two blocks gets two headings, and an id may appear once.
    ident = f' id="{_sheet_anchor(archivo)}"' if with_id else ""
    return (
        f'<a class="{clase}"{ident} href="{base}/{esc_year}/{esc_month}'
        f'?hoja={esc_archivo}{extra}#{_sheet_anchor(archivo)}">'
        f'<span>{html.escape(_sheet_link_label(review_ref))}</span></a>'
    )


def editor(
    year: str,
    month: str,
    entries: list[dict],
    token: str,
    sheets: dict,
    *,
    selected_hoja: str | None = None,
    all_sheets: dict | None = None,
    showing_all: bool = True,
    months: list | None = None,
    candidates: dict | None = None,
    date_checks: dict | None = None,
    sheet_blocks: dict | None = None,
    section: str = "seguridad",
    tag_counts: dict | None = None,
    tag_filter: str = "",
    moved_to: str = "",
) -> str:
    """The middle and right panes plus the sidebar's list of sheets to check.

    *section* only decides where the links point; the caller has already
    narrowed entries and sheets to that section's.

    *sheets* is a mapping of the sort review_pages() returns: a locator to
    how many doubtful entries it holds. The flag is a plain link to this same
    page carrying that sheet's reference as a query parameter -- there is no
    script required to open it, only a second page load, which is the whole
    point: a click that depends on JavaScript having loaded is a click that
    can silently do nothing.

    *selected_hoja* is the reference the dashboard already validated against
    the database (see dashboard._selected_sheet); this function only decides
    what to render for it, never whether it is trustworthy.
    """
    esc_year = html.escape(str(year))
    esc_month = html.escape(str(month))
    esc_token = html.escape(str(token))
    tag_filter = tag_filter if tag_filter in SLUGS else ""
    # Seguridad's one block keeps its heading; Mantenimiento shows its
    # subheadings as tags on the lines instead, so a day is never split
    # across four headings.
    agrupar = section != "mantenimiento"
    # What every link to this same page carries, so opening a sheet keeps
    # the tag being shown, and choosing a tag keeps the sheet open.
    cola_modo = "" if showing_all else "&hojas=pendientes"
    cola_filtro = f"&bloque={tag_filter}" if tag_filter else ""
    cola_hoja = f"&hoja={html.escape(str(selected_hoja))}" if selected_hoja else ""

    # all_sheets is every sheet of the batch; sheets is the shortlist that
    # still has flags on it. Defaulting to the shortlist keeps every existing
    # caller (and the month whose database predates review_ref on confident
    # entries) behaving exactly as before.
    todas = all_sheets if all_sheets is not None else sheets
    mostradas = todas if showing_all else sheets
    base = SECTION_PATHS.get(section, "/mes")
    vista = _view_fields(selected_hoja, showing_all, section, tag_filter)
    selector_meses = _month_list(months or [], year, month, base)

    # Two headings, not one: the block, and the sheet the lines under it came
    # off. Entries arrive in date order (see entry_store.sheet_order), so a
    # sheet's lines are always contiguous and a heading each time the
    # reference changes groups them without reordering anything.
    # Sheets no line points at -- a sheet the reading found nothing on, or
    # one whose lines were all filed elsewhere -- still get their place in
    # the document, between their neighbours in date order, so the pages
    # run without gaps and an empty one can be opened and filled in.
    con_lineas = {e.get("review_ref") for e in entries if e.get("review_ref")}
    bloques = sheet_blocks or {}
    vacias: dict[str, list[str]] = {}
    # A filtered view shows only the sheets with a line under that tag.
    for ref in sorted((r for r in todas if r not in con_lineas and not tag_filter),
                      key=sheet_order):
        vacias.setdefault(bloques.get(ref, "") if agrupar else "", []).append(ref)

    filas = []
    bloque_actual = None
    hoja_actual = None
    con_id: set[str] = set()

    def vaciar(bloque, hasta=None):
        """Emit the empty sheets of *bloque* that come before *hasta*."""
        pendientes = vacias.get(bloque, [])
        while pendientes and (hasta is None or sheet_order(pendientes[0]) < sheet_order(hasta)):
            ref = pendientes.pop(0)
            con_id.add(ref)
            filas.append(_sheet_heading(ref, esc_year, esc_month, selected_hoja, base=base,
                                        extra=cola_modo + cola_filtro))
            filas.append(_date_control(ref, str(year), str(month), esc_token, vista,
                                       (date_checks or {}).get(ref)))
            filas.append(_empty_sheet(ref, esc_token, vista, confirmed=ref not in sheets))

    for entry in entries:
        bloque = entry.get("block", "") if agrupar else ""
        if bloque != bloque_actual:
            if bloque_actual is not None:
                vaciar(bloque_actual)
            bloque_actual = bloque
            hoja_actual = None
            if agrupar:
                filas.append(f'<h3 class="titulo-bloque">{html.escape(str(bloque))}</h3>')
        hoja = entry.get("review_ref") or ""
        candidatos = (candidates or {}).get(entry.get("id"), []) if not hoja else []
        # A run of unrecorded lines is one group only while they share the
        # same candidates; different candidates are different gaps.
        clave = hoja or ("?", tuple(candidatos))
        if clave != hoja_actual:
            hoja_actual = clave
            if hoja:
                vaciar(bloque, hoja)
                primera = hoja not in con_id
                con_id.add(hoja)
                filas.append(_sheet_heading(hoja, esc_year, esc_month, selected_hoja,
                                            with_id=primera, base=base,
                                            extra=cola_modo + cola_filtro))
                if primera:
                    filas.append(_date_control(hoja, str(year), str(month), esc_token,
                                               vista, (date_checks or {}).get(hoja)))
            else:
                filas.append(_unconfirmed_heading(
                    candidatos, esc_year, esc_month, entry.get("id"), selected_hoja, base,
                    extra=cola_modo + cola_filtro))
            filas.append(_add_line(esc_token, vista, before_id=entry.get("id")))
        filas.append(_entry_row(entry, esc_token, esc_year, esc_month, selected_hoja, vista,
                                _assign_sheet(entry.get("id"), candidatos, esc_token, vista),
                                etiqueta="" if agrupar else _tag_chip(entry, esc_token, vista),
                                tag_slug="" if agrupar else slug_of(entry.get("block", ""))))
        filas.append(_add_line(esc_token, vista, after_id=entry.get("id")))
    if bloque_actual is not None:
        vaciar(bloque_actual)
    # A block with no lines at all: its sheets still belong in the document.
    for bloque in [b for b in vacias if vacias[b]]:
        if agrupar:
            filas.append(f'<h3 class="titulo-bloque">{html.escape(str(bloque) or "Hojas")}</h3>')
        vaciar(bloque)
    vacio = ("No hay anotaciones de este apartado en este mes." if tag_filter
             else "No hay anotaciones en este mes.")
    cuerpo_documento = (
        "\n".join(filas) if filas else f'<p class="vacio">{vacio}</p>'
    )
    if not agrupar and tag_counts is not None:
        cuerpo_documento = (
            _filter_bar(tag_counts, tag_filter, f"{base}/{esc_year}/{esc_month}",
                        keep=cola_hoja + cola_modo)
            + "\n" + _moved_notice(moved_to)
            + cuerpo_documento
        )

    elementos_hojas = []
    for referencia, cuenta in mostradas.items():
        nombre_archivo = image_name(referencia)
        esc_archivo = html.escape(nombre_archivo)
        # A symbol, not a sentence: an amber mark with the count while a
        # sheet still has doubtful lines, a green tick once it has none, and
        # an empty circle when it has no lines at all. The words stay in the
        # tooltip for whoever wants them.
        if cuenta:
            detalle = "1 anotación dudosa" if cuenta == 1 else f"{cuenta} anotaciones dudosas"
            estado = (f'<span class="estado-hoja pendiente">{_ICONO_MARCA}</span>')
            cifra = f'<span class="cuenta-dudas">{cuenta}</span>'
            clase = "hoja-pendiente"
        elif referencia not in con_lineas and referencia in sheets:
            # Nothing to revise is not the same as revised: a sheet with no
            # lines -- the reading found nothing, or every line went to
            # another sheet -- showed the green tick, as though checked.
            detalle = "Sin anotaciones: no hay ninguna línea en esta hoja"
            estado = f'<span class="estado-hoja vacia">{_ICONO_VACIA}</span>'
            cifra = ""
            clase = "hoja-pendiente vacia"
        elif referencia in sheets:
            # Clean lines, but a date that does not fit the scan: still to
            # check, and the tick would say otherwise.
            detalle = "Fecha por confirmar: no encaja con las hojas de al lado"
            estado = f'<span class="estado-hoja pendiente">{_ICONO_MARCA}</span>'
            cifra = ""
            clase = "hoja-pendiente"
        else:
            detalle = ("Revisada: hoja vacía" if referencia not in con_lineas
                       else "Revisada: ninguna anotación dudosa")
            estado = f'<span class="estado-hoja revisada">{_ICONO_REVISADA}</span>'
            cifra = ""
            clase = "hoja-pendiente revisada"
        if selected_hoja and nombre_archivo == selected_hoja:
            clase += " seleccionada"
        elementos_hojas.append(
            f'<li><a href="{base}/{esc_year}/{esc_month}?hoja={esc_archivo}'
            f'{cola_modo}{cola_filtro}#{_sheet_anchor(nombre_archivo)}" '
            f'class="{clase}" data-hoja="{esc_archivo}" title="{html.escape(detalle)}">'
            f'{estado}<span class="nombre-en-lista">'
            f'{html.escape(_sheet_short_label(referencia))}</span>{cifra}</a></li>'
        )
    vacio = (
        "Este mes no tiene hojas." if showing_all
        else "No quedan hojas por revisar."
    )
    lista_hojas = (
        "\n".join(elementos_hojas) if elementos_hojas
        else f'<li class="vacio">{vacio}</li>'
    )

    # Keeping ?hoja= on both links means switching the list does not throw
    # away the sheet being read.
    cola = f"&hoja={html.escape(str(selected_hoja))}" if selected_hoja else ""
    modo_hojas = (
        '<div class="modo-hojas">'
        # Todas first: it is the default, so it sits where the eye starts.
        f'<a href="{base}/{esc_year}/{esc_month}?hojas=todas{cola}{cola_filtro}" '
        f'class="{"activo" if showing_all else ""}">Todas ({len(todas)})</a>'
        f'<a href="{base}/{esc_year}/{esc_month}?hojas=pendientes{cola}{cola_filtro}" '
        f'class="{"" if showing_all else "activo"}">Por revisar ({len(sheets)})</a>'
        '</div>'
    )

    if selected_hoja:
        esc_selected = html.escape(str(selected_hoja))
        # The file's name as the colleague reads it: without the maintenance
        # mark that only keeps it apart from a security sheet's.
        esc_visible = html.escape(str(selected_hoja).removeprefix(MAINTENANCE_IMAGE_PREFIX))
        # A plain link to the same image, working with no script at all: it
        # opens the full-resolution scan on its own, where the browser's own
        # zoom and pan already do the job. The click listener in _SCRIPT
        # upgrades this into an in-place zoom when it can; when it can't,
        # this anchor is the whole feature.
        # Three plain forms, not a script: turning the sheet rewrites the
        # file, and the rule for anything that writes is a form that posts
        # and redirects. The angles are named clockwise, the way the arrows
        # on the buttons point.
        giros = "".join(
            f'<form method="post" action="/hoja/{esc_selected}/girar">'
            f'<input type="hidden" name="csrf" value="{esc_token}">{vista}'
            f'<input type="hidden" name="grados" value="{grados}">'
            f'<button type="submit" class="boton-girar" title="{titulo}">'
            f'{simbolo}</button></form>'
            for grados, simbolo, titulo in (
                (270, "&#8634;", "Girar a la izquierda"),
                (90, "&#8635;", "Girar a la derecha"),
                (180, "&#8693;", "Poner del derecho"),
            )
        )
        # Walking the batch sheet by sheet, over every sheet rather than
        # only the flagged ones: the flags are a shortlist, and someone
        # checking the whole month against the paper has to be able to reach
        # a sheet nothing was flagged on.
        orden = [image_name(referencia) for referencia in todas]
        try:
            indice = orden.index(str(selected_hoja))
        except ValueError:
            indice = -1
        cola_modo = "" if showing_all else "&hojas=pendientes"

        def _paso(destino: int, simbolo: str, titulo: str) -> str:
            if indice < 0 or not 0 <= destino < len(orden):
                return f'<span aria-hidden="true">{simbolo}</span>'
            esc_destino = html.escape(orden[destino])
            return (
                f'<a href="{base}/{esc_year}/{esc_month}?hoja={esc_destino}'
                f'{cola_modo}{cola_filtro}#{_sheet_anchor(orden[destino])}" '
                f'title="{titulo}">{simbolo}</a>'
            )

        posicion = (
            f'<span class="posicion-hoja">{indice + 1} / {len(orden)}</span>'
            if indice >= 0 else ""
        )
        paso = (
            '<div class="paso-hoja">'
            + _paso(indice - 1, "&#8249;", "Hoja anterior")
            + _paso(indice + 1, "&#8250;", "Hoja siguiente")
            + posicion
            + "</div>"
        )
        # The sheet's date, set right beside the paper it is read from. It
        # is under the sheet's heading in the document too, but a sheet with
        # no lines filed under it has no heading -- most of the undated ones.
        ref_abierta = next((r for r in todas if image_name(r) == selected_hoja), None)
        fecha_abierta = (
            _date_control(ref_abierta, str(year), str(month), esc_token, vista,
                          (date_checks or {}).get(ref_abierta))
            if ref_abierta else ""
        )
        panel_imagen_contenido = (
            '<div class="barra-hoja">'
            f'<span class="nombre-hoja" title="{esc_visible}">{esc_visible}</span>'
            f'<div class="giros">{paso}{_CONTROLES_ZOOM}{giros}</div>'
            '</div>'
            f'{fecha_abierta}'
            '<div class="visor-hoja">'
            f'<a class="enlace-imagen" href="/hoja/{esc_selected}" '
            'title="Abrir la hoja a tamaño completo">'
            '<img class="imagen-hoja" alt="Hoja escaneada, tal como llegó" '
            f'src="/hoja/{esc_selected}"></a>'
            '</div>'
        )
    else:
        panel_imagen_contenido = (
            '<p class="sin-hoja">No hay ninguna hoja seleccionada.</p>'
        )

    return f"""<div class="disposicion" data-lateral="abierto">
  <aside class="panel-lateral">
    <h2>{esc_month} {esc_year}</h2>
    {selector_meses}
    <h3>Hojas</h3>
    {modo_hojas}
    <div class="leyenda-hojas" aria-hidden="true">
      <span><span class="estado-hoja pendiente">{_ICONO_MARCA}</span>Por revisar</span>
      <span><span class="estado-hoja revisada">{_ICONO_REVISADA}</span>Revisada</span>
      <span><span class="estado-hoja vacia">{_ICONO_VACIA}</span>Sin anotaciones</span>
    </div>
    <ul class="lista-hojas">
{lista_hojas}
    </ul>
  </aside>
  <section class="panel-documento">
    <div class="entradas">
{cuerpo_documento}
    </div>
  </section>
  <div class="divisor-imagen" role="separator" aria-orientation="vertical"
       tabindex="0" title="Arrastrar para cambiar el ancho de la hoja"
       aria-label="Cambiar el ancho del panel de la hoja"></div>
  <aside class="panel-imagen">
    {panel_imagen_contenido}
  </aside>
</div>"""


def save_control(
    year: str, month: str, token: str, *,
    selected_hoja: str | None = None, showing_all: bool = True,
    section: str = "seguridad", tag_filter: str = "",
) -> str:
    """Guardar, for the command bar: every line, then the .docx.

    It used to sit at the top of the middle pane, which scrolls -- and opening
    a sheet scrolls that pane to the sheet's heading, so the button was out of
    sight almost every time anyone looked for it. In the command bar it is
    always there, the way Save is in Word. The count of unsaved lines sits
    beside it; Ctrl+S submits this same form.
    """
    esc_year = html.escape(str(year))
    esc_month = html.escape(str(month))
    return (
        '<div class="control-guardar">'
        '<span class="estado-guardado" id="estado-guardado" aria-live="polite"></span>'
        f'<form method="post" action="/guardar/{esc_year}/{esc_month}" id="form-guardar">'
        f'<input type="hidden" name="csrf" value="{html.escape(str(token))}">'
        f'{_view_fields(selected_hoja, showing_all, section, tag_filter)}'
        '<button type="submit" class="boton-guardar" '
        'title="Guarda todas las líneas. Con todas las hojas revisadas, genera el '
        'documento final (Ctrl+S)">'
        f'{_ICONO_GUARDAR}<span>Guardar</span></button>'
        '</form></div>'
    )


def summary(stats: dict, advanced: bool) -> str:
    """The command bar's counts. The colleague sees what is left to check;
    the author additionally sees spend, model and per-sheet totals.
    """
    pendientes = html.escape(str(stats.get("pendientes", 0)))
    anotaciones = html.escape(str(stats.get("anotaciones", 0)))
    documento = html.escape(str(stats.get("documento", "")))
    try:
        porcentaje = max(0, min(100, int(stats.get("revisado", 0))))
    except (TypeError, ValueError):
        porcentaje = 0
    en_linea = bool(stats.get("sistema"))
    estado_clase = "estado-ok" if en_linea else "estado-error"
    estado_texto = "Sistema en línea" if en_linea else "Sistema sin conexión"

    # The count he acts on reads as one figure with its own weight; every
    # other number here is supporting detail, set off by a hairline rather
    # than competing with it for attention.
    piezas = [f"""<div class="resumen">
  <div class="resumen-principal">
    <span class="resumen-cifra pendientes">{pendientes}</span>
    <span class="resumen-etiqueta">por revisar</span>
  </div>
  <div class="resumen-detalle">
    <span class="anotaciones">{anotaciones} anotaciones</span>
    <div class="barra-revisado" role="progressbar" aria-valuenow="{porcentaje}"
         aria-valuemin="0" aria-valuemax="100">
      <div class="barra-revisado-relleno" style="width:{porcentaje}%"></div>
    </div>
    <span class="documento">{documento}</span>
    <span class="{estado_clase}">{estado_texto}</span>
  </div>
</div>"""]

    if advanced:
        gasto = html.escape(str(stats.get("gasto", "")))
        tope = html.escape(str(stats.get("tope", "")))
        try:
            proporcion = max(0, min(100, round(
                float(stats.get("gasto", 0)) / float(stats.get("tope", 1)) * 100
            )))
        except (TypeError, ValueError, ZeroDivisionError):
            # "sin datos" is a real value for gasto; a bar is not honest then.
            proporcion = None
        barra_gasto = (
            f'<div class="barra-gasto" role="progressbar" aria-valuenow="{proporcion}"'
            ' aria-valuemin="0" aria-valuemax="100">'
            f'<div class="barra-gasto-relleno" style="width:{proporcion}%"></div></div>'
            if proporcion is not None else ""
        )
        campos = "".join(
            f'<div class="dato-avanzado"><span class="dato-etiqueta">{etiqueta}</span>'
            f'<span class="dato-valor">{valor}</span></div>'
            for etiqueta, valor in (
                ("Modelo", html.escape(str(stats.get("modelo", "")))),
                ("Hojas leídas", html.escape(str(stats.get("hojas", "")))),
                ("Marcadas", html.escape(str(stats.get("marcadas", "")))),
                ("Corregidas a mano", html.escape(str(stats.get("corregidas", "")))),
            )
        )
        # Spend leads: it is the number with a limit behind it, and the only
        # one that stops the system working when it runs out.
        piezas.append(f"""<div class="resumen-avanzado" id="resumen-avanzado">
  <div class="gasto-avanzado">
    <span class="dato-etiqueta">Gasto del mes</span>
    <span class="gasto-cifra">{gasto} €</span>
    <span class="gasto-tope">de {tope} €</span>
    {barra_gasto}
  </div>
  <div class="datos-avanzados">{campos}</div>
</div>""")

    return "\n".join(piezas)

