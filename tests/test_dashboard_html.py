"""Rendering: Spanish throughout, both palettes, short movement, escaped."""

import re
from typing import ClassVar

import pytest

from dashboard_html import _SCRIPT, STYLESHEET, editor, page, summary


def an_entry(**over):
    entry = {"id": 1, "block": "Intervenciones Seguridad:", "position": 0,
             "text": "Se retiran pilonas.", "flagged": 0, "review_ref": "",
             "hand_edited": 0, "original_text": "Se retiran pilonas."}
    entry.update(over)
    return entry


class TestLanguage:
    ENGLISH = ("Save", "Sheet", "Month", "Entry", "Review", "Settings", "Loading")

    def test_the_page_carries_no_english(self):
        html = page("Septiembre", editor("2026", "SEPTIEMBRE", [an_entry()], "t", {}))
        for word in self.ENGLISH:
            assert not re.search(rf">\s*{word}\b", html), word

    def test_the_buttons_are_spanish(self):
        html = editor("2026", "SEPTIEMBRE", [an_entry()], "t", {})
        assert "Guardar" in html

    def test_the_sections_are_spanish(self):
        html = page("x", "y")
        assert "Seguridad" in html and "Mantenimiento" in html


class TestTheme:
    ROLES = ("--page", "--surface", "--text", "--muted", "--border",
             "--accent", "--flag", "--ok", "--error")

    @pytest.mark.parametrize("role", ROLES)
    def test_both_themes_define_every_role(self, role):
        light, dark = STYLESHEET.split("[data-tema=\"oscuro\"]", 1)
        assert role in light, f"{role} missing from claro"
        assert role in dark, f"{role} missing from oscuro"

    def test_the_exact_palette_is_used(self):
        for colour in ("#f3f2f1", "#ffffff", "#0f6cbd", "#b8860b",
                       "#1f1f1f", "#2b2b2b", "#4aa3e0", "#d8a12a"):
            assert colour in STYLESHEET, colour

    def test_the_sheet_image_is_never_tinted(self):
        assert "filter:" not in STYLESHEET.replace("filter: none", "")


class TestMovement:
    def test_nothing_lasts_longer_than_150ms(self):
        for value in re.findall(r"(\d+)ms", STYLESHEET):
            assert int(value) <= 150, f"{value}ms is too long"

    def test_seconds_are_not_used_to_smuggle_in_a_long_one(self):
        assert not re.search(r"transition[^;]*\b\d*\.?\d+s\b", STYLESHEET)

    def test_reduced_motion_is_respected(self):
        assert "prefers-reduced-motion" in STYLESHEET


class TestEscaping:
    def test_entry_text_is_escaped(self):
        html = editor("2026", "SEPTIEMBRE",
                      [an_entry(text="<script>alert(1)</script>")], "t", {})
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html

    def test_the_month_name_is_escaped(self):
        assert "<b>" not in editor("2026", "<b>", [an_entry()], "t", {})


class TestSheetLink:
    def test_the_lines_of_a_sheet_sit_under_a_heading_that_opens_it(self):
        """Supersedes a per-line "Ver hoja del ..." link. The lines are
        grouped by sheet now, so repeating the link on every row printed the
        same text over and over down the page."""
        html_out = editor(
            "2026", "SEPTIEMBRE",
            [an_entry(review_ref="20-09-2026 p39")], "t", {},
        )
        assert "?hoja=20-09-2026_p39.jpg" in html_out
        assert 'id="entrada-1"' in html_out
        assert "cabecera-hoja" in html_out
        assert "20-09-2026" in html_out
        assert "enlace-hoja" not in html_out

    def test_one_heading_for_a_run_of_lines_off_the_same_sheet(self):
        html_out = editor(
            "2026", "SEPTIEMBRE",
            [an_entry(id=1, review_ref="20-09-2026 p39"),
             an_entry(id=2, review_ref="20-09-2026 p39"),
             an_entry(id=3, review_ref="21-09-2026 p41")],
            "t", {},
        )
        assert html_out.count("cabecera-hoja") == 2

    def test_an_entry_with_no_review_ref_says_so(self):
        html_out = editor("2026", "SEPTIEMBRE", [an_entry(review_ref="")], "t", {})
        assert "enlace-hoja" not in html_out
        assert "Página no registrada" in html_out

    def test_the_row_of_the_selected_sheet_is_marked(self):
        html_out = editor(
            "2026", "SEPTIEMBRE",
            [an_entry(review_ref="20-09-2026 p39")], "t", {},
            selected_hoja="20-09-2026_p39.jpg",
        )
        assert "hoja-actual" in html_out


class TestTextareaSize:
    def test_the_textarea_defaults_to_several_lines(self):
        html = editor("2026", "SEPTIEMBRE", [an_entry()], "t", {})
        assert 'rows="3"' in html

    def test_the_textarea_stays_resizable(self):
        assert "resize: vertical" in STYLESHEET

    def test_every_box_is_the_same_width(self):
        """Supersedes an earlier 400px flex-basis floor. That floor made the
        width depend on what else the row held, so a row with a sheet link
        got a narrower box than one without, and the rows stepped in and out
        down the page. The width now comes from the grid column instead."""
        caja = re.search(r"\.texto-entrada\s*{([^}]*)}", STYLESHEET).group(1)
        assert "width: 100%" in caja, "the box fills its column"
        assert "flex:" not in caja, "the width must not depend on the row's content"

        fila = re.search(r"\.fila-entrada\s*{([^}]*)}", STYLESHEET).group(1)
        assert "display: grid" in fila
        # A fixed button column, so each row's grid agrees with every other's.
        assert "var(--ancho-acciones)" in fila
        assert "--ancho-acciones:" in STYLESHEET

    def test_the_row_holds_only_the_text_and_its_buttons(self):
        """The sheet link used to be a nowrap flex sibling in this row that
        refused to shrink, so it was drawn over the "Guardar línea" button.
        It now lives in the heading above the sheet's run of lines, so the
        row has nothing left to collide with."""
        fila = re.search(r"\.fila-entrada\s*{([^}]*)}", STYLESHEET).group(1)
        assert "enlace" not in fila
        assert ".enlace-hoja" not in STYLESHEET

    def test_the_panels_are_responsive(self):
        assert "@media (max-width: 1100px)" in STYLESHEET
        assert "@media (max-width: 700px)" in STYLESHEET

    def test_the_layout_fills_the_window_without_hardcoding_the_bars(self):
        """calc(100vh - 49px) counted the command bar and forgot the summary
        bar under it, so the panels ran past the bottom of the window."""
        # The declaration, not the word: the comment explaining why it is
        # gone naturally names it.
        sin_comentarios = re.sub(r"/\*.*?\*/", "", STYLESHEET, flags=re.S)
        assert "100vh" not in sin_comentarios
        disposicion = re.search(r"\.disposicion\s*{([^}]*)}", STYLESHEET).group(1)
        assert "min-height: 0" in disposicion


class TestAdvanced:
    STATS: ClassVar[dict] = {"pendientes": 7, "anotaciones": 148, "dias": 21,
             "revisado": 82, "guardado": "hace 2 horas", "sistema": True,
             "gasto": "3.90", "tope": "5.50", "modelo": "gpt-5.4",
             "hojas": 84, "marcadas": 118, "corregidas": 23}

    def test_the_colleague_does_not_see_the_numbers(self):
        html = summary(self.STATS, advanced=False)
        assert "gpt-5.4" not in html
        assert "5.50" not in html
        assert "7" in html, "he still sees what is left to check"

    def test_the_author_does(self):
        html = summary(self.STATS, advanced=True)
        assert "gpt-5.4" in html and "5.50" in html


class TestCsrf:
    def test_the_csrf_field_renders_exactly(self):
        html = editor("2026", "SEPTIEMBRE", [an_entry()], "TOKEN", {})
        assert '<input type="hidden" name="csrf" value="TOKEN">' in html


class TestSheetImage:
    """The flag's entire purpose: without this, clicking it did nothing."""

    SHEETS: ClassVar[dict] = {"01-09-2026 p1": 1}

    def test_a_selected_sheet_renders_its_image(self):
        html = editor("2026", "SEPTIEMBRE", [an_entry()], "t", self.SHEETS,
                      selected_hoja="01-09-2026_p1.jpg")
        assert '<img class="imagen-hoja"' in html
        assert 'src="/hoja/01-09-2026_p1.jpg"' in html

    def test_no_selection_renders_no_image_and_says_so_in_spanish(self):
        html = editor("2026", "SEPTIEMBRE", [an_entry()], "t", self.SHEETS)
        assert "<img" not in html
        assert "seleccionada" in html

    def test_the_flag_is_a_plain_link_to_the_month_route(self):
        html = editor("2026", "SEPTIEMBRE", [an_entry()], "t", self.SHEETS)
        assert 'href="/mes/2026/SEPTIEMBRE?hoja=01-09-2026_p1.jpg#hoja-01-09-2026_p1.jpg"' in html

    def test_the_selected_flag_reads_as_selected_in_the_sidebar(self):
        html = editor("2026", "SEPTIEMBRE", [an_entry()], "t", self.SHEETS,
                      selected_hoja="01-09-2026_p1.jpg")
        assert "seleccionada" in html.split("panel-imagen")[0]


class TestImagePanel:
    """Zoomable without a network fetch: a link to the sheet's own /hoja/
    URL, plus a resizable panel with a floor so it never collapses away."""

    SHEETS: ClassVar[dict] = {"01-09-2026 p1": 1}

    def test_the_image_is_wrapped_in_a_link_to_its_own_full_size_url(self):
        html = editor("2026", "SEPTIEMBRE", [an_entry()], "t", self.SHEETS,
                      selected_hoja="01-09-2026_p1.jpg")
        assert re.search(
            r'<a class="enlace-imagen" href="/hoja/01-09-2026_p1\.jpg"[^>]*>'
            r'\s*<img class="imagen-hoja"',
            html,
        ), "clicking the image must open its own full-resolution scan"

    def test_the_panel_declares_a_resize_and_a_floor(self):
        assert "resize: horizontal" in STYLESHEET
        block = re.search(r"\.panel-imagen\s*{([^}]*)}", STYLESHEET).group(1)
        assert "min-width" in block


class TestBlockHeadings:
    def test_each_blocks_name_is_rendered_as_a_heading(self):
        entries = [
            an_entry(id=1, block="Intervenciones Seguridad:"),
            an_entry(id=2, block="Mantenimiento Ascensores:"),
        ]
        html = editor("2026", "SEPTIEMBRE", entries, "t", {})
        assert "Intervenciones Seguridad:" in html
        assert "Mantenimiento Ascensores:" in html


class TestTheSidebar:
    def test_the_list_scrolls(self):
        """It was overflow: hidden, so a month with sixty-odd sheets showed
        the first few and there was no way to reach the rest."""
        panel = re.search(r"\.panel-lateral\s*{([^}]*)}", STYLESHEET).group(1)
        assert "overflow: hidden" not in panel
        lista = re.search(r"\.lista-hojas\s*{([^}]*)}", STYLESHEET).group(1)
        assert "overflow-y: auto" in lista
        assert "min-height: 0" in lista

    def test_collapsing_leaves_no_stub(self):
        """A zero-width grid column does not hide padding or a border."""
        cerrado = re.search(
            r'\.disposicion\[data-lateral="cerrado"\] \.panel-lateral\s*{([^}]*)}',
            STYLESHEET,
        ).group(1)
        assert "padding: 0" in cerrado
        assert "border-right: none" in cerrado

    def test_the_icon_flips_with_the_panel(self):
        assert '[data-lateral="cerrado"] .icono-abrir-lateral { display: block; }' in STYLESHEET
        assert '[data-lateral="cerrado"] .icono-cerrar-lateral { display: none; }' in STYLESHEET

    def test_no_nul_byte_reaches_the_page(self):
        """The old arrow was content: "\\00ab" inside a Python string, which
        Python read as an octal escape: a NUL byte and the letters "ab"."""
        assert "\x00" not in STYLESHEET
        assert "\x00" not in page("t", "")

    def test_both_toggles_have_real_icons(self):
        html_out = page("t", "")
        assert "icono-cerrar-lateral" in html_out and "icono-abrir-lateral" in html_out
        assert "icono-luna" in html_out and "icono-sol" in html_out


class TestTheSheetZoom:
    """It was one class toggle -- fit the panel, or natural size, nothing
    between -- on the one image in the product people have to read
    handwriting off."""

    def _panel(self):
        return editor("2026", "SEPTIEMBRE", [an_entry()], "t", {},
                      selected_hoja="20-09-2026_p39.jpg")

    def test_the_controls_are_there(self):
        html_out = self._panel()
        for control in ("zoom-menos", "zoom-mas", "nivel-zoom"):
            assert f'id="{control}"' in html_out

    def test_the_controls_start_hidden_for_a_browser_with_no_script(self):
        """They do nothing without the script, so the script reveals them."""
        html_out = self._panel()
        assert '<div class="zoom-hoja" id="zoom-hoja" hidden>' in html_out
        assert "controlesZoom.hidden = false" in _SCRIPT

    def test_the_no_script_fallback_survives(self):
        """With no script the anchor still opens the full scan on its own."""
        html_out = self._panel()
        assert 'class="enlace-imagen" href="/hoja/20-09-2026_p39.jpg"' in html_out

    def test_there_are_several_zoom_steps(self):
        pasos = re.search(r"var PASOS = \[([^\]]*)\]", _SCRIPT).group(1)
        assert len([p for p in pasos.split(",") if p.strip()]) >= 6

    def test_the_image_can_be_panned_when_it_overflows(self):
        assert ".imagen-hoja.desplazable" in STYLESHEET
        assert ".imagen-hoja.agarrando" in STYLESHEET
        assert ".visor-hoja.arrastrando" in STYLESHEET

    def test_the_toolbar_does_not_move_with_the_image(self):
        """position: sticky holds on the vertical axis and slides away the
        moment a zoomed sheet is scrolled sideways. The toolbar is now a
        fixed flex row and only the viewer under it scrolls."""
        barra = re.search(r"\.barra-hoja\s*{([^}]*)}", STYLESHEET).group(1)
        assert "position: sticky" not in barra
        assert "flex: none" in barra
        visor = re.search(r"\.visor-hoja\s*{([^}]*)}", STYLESHEET).group(1)
        assert "overflow: auto" in visor
        assert '<div class="visor-hoja">' in self._panel()

    def test_the_panel_can_be_made_much_bigger(self):
        """Supersedes CSS resize: horizontal. That grip sits on the bottom-
        right corner and grows the box rightwards, and this is the rightmost
        column: there was nowhere to grow and no hold on the left edge. A
        splitter between the document and the sheet does it instead."""
        panel = re.search(r"\.panel-imagen\s*{([^}]*)}", STYLESHEET).group(1)
        assert "resize: horizontal" not in panel
        assert "max-width: 85vw" in panel

    def test_there_is_a_splitter_on_the_left_edge_of_the_sheet(self):
        html_out = self._panel()
        divisor = html_out.index('class="divisor-imagen"')
        assert divisor < html_out.index('<aside class="panel-imagen">')
        assert divisor > html_out.index('<section class="panel-documento">')
        assert 'role="separator"' in html_out
        assert 'tabindex="0"' in html_out

    def test_the_splitter_has_its_own_grid_track(self):
        disposicion = re.search(r"\.disposicion\s*{([^}]*)}", STYLESHEET).group(1)
        assert "minmax(0, 1fr) 6px auto" in disposicion
        assert ('.disposicion[data-lateral="cerrado"] '
                '{ grid-template-columns: 0 minmax(0, 1fr) 6px auto; }') in STYLESHEET

    def test_dragging_and_the_keyboard_both_work(self):
        assert "setPointerCapture" in _SCRIPT
        assert "'ArrowLeft'" in _SCRIPT and "'ArrowRight'" in _SCRIPT

    def test_the_document_cannot_be_squeezed_out(self):
        assert "DOCUMENTO_MIN" in _SCRIPT

    def test_the_old_single_step_toggle_is_gone(self):
        assert "ampliada" not in STYLESHEET
        assert "ampliada" not in self._panel()


class TestTheAdvancedSwitch:
    """The technical numbers were always on for an entitled address, laid out
    as a flat row of spans under the summary."""

    STATS: ClassVar[dict] = {
        "pendientes": 7, "anotaciones": 148, "guardado": "08:59",
        "revisado": 82, "sistema": True, "gasto": "3.22", "tope": "5.00",
        "modelo": "gpt-5.4", "hojas": 84, "marcadas": 118, "corregidas": 23,
    }

    def test_the_numbers_stay_out_of_an_unentitled_page(self):
        """The switch is a display control, not the gate: an address that may
        not see these never receives them in the markup at all."""
        plain = summary(self.STATS, False)
        assert "3.22" not in plain
        assert "gpt-5.4" not in plain
        assert "resumen-avanzado" not in plain
        assert 'id="alternar-avanzado"' not in page("t", plain, advanced=False)

    def test_the_switch_appears_only_for_an_entitled_address(self):
        assert 'id="alternar-avanzado"' in page("t", "", advanced=True)
        assert 'id="alternar-avanzado"' not in page("t", "", advanced=False)

    def test_the_card_is_hidden_until_the_switch_is_on(self):
        assert ".resumen-avanzado { display: none; }" in STYLESHEET
        assert '[data-avanzado="si"] .resumen-avanzado' in STYLESHEET

    def test_the_switch_starts_off(self):
        assert 'aria-pressed="false"' in page("t", "", advanced=True)
        assert "leer(AVANZADO_CLAVE) === 'si' ? 'si' : 'no'" in _SCRIPT

    def test_spend_leads_and_carries_its_share_of_the_cap(self):
        block = summary(self.STATS, True)
        assert "gasto-cifra" in block
        assert "3.22" in block and "5.00" in block
        # 3.22 of 5.00 is 64%.
        assert 'style="width:64%"' in block

    def test_no_bar_is_drawn_when_the_spend_is_unknown(self):
        """"sin datos" is a real value for gasto; a bar would be a lie."""
        block = summary({**self.STATS, "gasto": "sin datos"}, True)
        assert "sin datos" in block
        assert "barra-gasto-relleno" not in block

    def test_every_figure_is_labelled(self):
        block = summary(self.STATS, True)
        for etiqueta in ("Gasto del mes", "Modelo", "Hojas leídas",
                         "Marcadas", "Corregidas a mano"):
            assert etiqueta in block


class TestTheSheetHeading:
    def test_it_names_the_sheet_rather_than_instructing(self):
        """It read "Ver hoja del 20-09-2026 (página 39)" when it was a link
        beside a single line. A heading over a run of lines names them."""
        html_out = editor("2026", "SEPTIEMBRE",
                          [an_entry(review_ref="20-09-2026 p39")], "t", {})
        assert "20-09-2026 · página 39" in html_out
        assert "Ver hoja" not in html_out

    def test_a_sheet_with_no_date_says_so(self):
        """It used to show the scan's name, SKM_C3082609, where every other
        heading shows a date."""
        html_out = editor("2026", "SEPTIEMBRE",
                          [an_entry(review_ref="SKM_C3082609 p7")], "t", {})
        assert "sin fecha · página 7" in html_out
        assert "SKM_C3082609 · página" not in html_out

    def test_the_heading_of_the_open_sheet_is_marked(self):
        html_out = editor("2026", "SEPTIEMBRE",
                          [an_entry(review_ref="20-09-2026 p39")], "t", {},
                          selected_hoja="20-09-2026_p39.jpg")
        assert "cabecera-hoja actual" in html_out

    def test_it_scrolls_with_its_lines(self):
        """Supersedes a sticky heading. With one per sheet they piled up at
        the top of the pane as it scrolled."""
        cabecera = re.search(r"\.cabecera-hoja\s*{([^}]*)}", STYLESHEET).group(1)
        assert "sticky" not in cabecera


class TestOpeningASheetFindsItsLines:
    def test_every_way_in_lands_on_the_heading(self):
        html_out = editor(
            "2026", "SEPTIEMBRE",
            [an_entry(id=1, review_ref="20-09-2026 p39"),
             an_entry(id=2, review_ref="21-09-2026 p41")],
            "t", {"20-09-2026 p39": 1, "21-09-2026 p41": 1},
            selected_hoja="20-09-2026_p39.jpg",
            all_sheets={"20-09-2026 p39": 1, "21-09-2026 p41": 1},
        )
        assert 'id="hoja-20-09-2026_p39.jpg"' in html_out
        # Heading, sidebar entry and the "next" arrow all carry the fragment.
        assert html_out.count("#hoja-21-09-2026_p41.jpg") >= 3

    def test_a_sheet_heading_twice_gets_the_id_once(self):
        html_out = editor(
            "2026", "SEPTIEMBRE",
            [an_entry(id=1, block="A:", review_ref="20-09-2026 p39"),
             an_entry(id=2, block="B:", review_ref="20-09-2026 p39")],
            "t", {},
        )
        assert html_out.count('id="hoja-20-09-2026_p39.jpg"') == 1

    def test_arriving_without_a_fragment_scrolls_to_the_open_sheet(self):
        assert "document.querySelector('.cabecera-hoja.actual')" in _SCRIPT
        assert "!location.hash" in _SCRIPT


class TestSidebarState:
    """"1 anotación dudosa" as text under every sheet read as clutter; the
    state is a symbol now, with the words kept in the tooltip."""

    def _sidebar(self, sheets, lines=(), to_check=None):
        entries = [an_entry(id=i + 1, review_ref=ref) for i, ref in enumerate(lines)]
        html_out = editor("2026", "SEPTIEMBRE", entries, "t",
                          sheets if to_check is None else to_check,
                          all_sheets=sheets, showing_all=True)
        return html_out[html_out.index('<ul class="lista-hojas">'):
                        html_out.index("</ul>")]

    def test_a_sheet_with_doubts_shows_a_mark_and_its_count(self):
        lista = self._sidebar({"20-09-2026 p39": 3})
        assert '<span class="estado-hoja pendiente">' in lista
        assert '<span class="cuenta-dudas">3</span>' in lista
        assert 'title="3 anotaciones dudosas"' in lista
        assert "anotaciones dudosas</span>" not in lista

    def test_a_checked_sheet_shows_a_tick_and_no_count(self):
        # Checked: in the month, no longer in Por revisar.
        lista = self._sidebar({"20-09-2026 p39": 0}, lines=["20-09-2026 p39"], to_check={})
        assert '<span class="estado-hoja revisada">' in lista
        assert "cuenta-dudas" not in lista

    def test_a_sheet_with_no_lines_is_empty_not_checked(self):
        """It showed the green tick, as though someone had checked it."""
        lista = self._sidebar({"20-09-2026 p39": 0})
        assert '<span class="estado-hoja vacia">' in lista
        assert "estado-hoja revisada" not in lista
        assert 'title="Sin anotaciones: no hay ninguna línea en esta hoja"' in lista

    def test_the_legend_names_all_three(self):
        html_out = editor("2026", "SEPTIEMBRE", [], "t", {})
        leyenda = html_out[html_out.index('class="leyenda-hojas"'):]
        leyenda = leyenda[:leyenda.index("</div>")]
        for palabra in ("Por revisar", "Revisada", "Sin anotaciones"):
            assert palabra in leyenda

    def test_the_label_is_short(self):
        assert "20-09-2026 · p39" in self._sidebar({"20-09-2026 p39": 1})
        assert "sin fecha · p27" in self._sidebar({"SKM_C30826092211360 p27": 1})

    def test_there_is_a_legend(self):
        html_out = editor("2026", "SEPTIEMBRE", [], "t", {})
        assert "leyenda-hojas" in html_out


class TestNoReloads:
    def test_buttons_are_sent_in_the_background(self):
        assert "evento.preventDefault();\n    if (document.body.classList.contains('ocupado'))" in _SCRIPT
        assert "fetch(accion, {" in _SCRIPT

    def test_the_fragment_that_used_to_jump_is_dropped(self):
        """Following the redirect put #entrada-N at the top edge of the pane,
        so a click mid-screen looked like a jump."""
        assert "history.replaceState(null, '', respuesta.url.split('#')[0])" in _SCRIPT

    def test_the_pane_keeps_its_scroll(self):
        assert "documento.scrollTop = desplazamiento" in _SCRIPT

    def test_the_forms_still_work_without_a_script(self):
        html_out = editor("2026", "SEPTIEMBRE", [an_entry()], "t", {})
        assert '<form class="acciones-entrada" method="post" action="/entradas/1">' in html_out

    def test_the_module_has_no_invalid_escapes(self):
        """A backslash in the script string is read by Python first: "\\00ab"
        once served a NUL byte, and "\\/" warns today and fails later."""
        import pathlib
        import warnings
        source = pathlib.Path(__file__).parent.parent.joinpath("dashboard_html.py").read_text()
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            compile(source, "dashboard_html.py", "exec")


class TestNoFlashAndNoReloadBetweenSheets:
    def test_saved_settings_are_applied_in_the_head(self):
        """The end-of-body script applied them after the first paint: every
        full load flashed the light theme and the default panel width."""
        html_out = page("t", "")
        head = html_out[:html_out.index("</head>")]
        from dashboard_html import _PRIMER_PINTADO
        assert f"<script>{_PRIMER_PINTADO}</script>" in head
        for key in ("memoria-tema", "memoria-lateral", "memoria-imagen-ancho-2"):
            assert key in _PRIMER_PINTADO

    def test_the_collapsed_sidebar_follows_the_root(self):
        assert 'html[data-lateral="cerrado"] .disposicion' in STYLESHEET

    def test_the_panel_width_is_a_variable_the_head_can_set(self):
        panel = re.search(r"\.panel-imagen\s*{([^}]*)}", STYLESHEET).group(1)
        assert "var(--ancho-imagen, 480px)" in panel

    def test_links_within_the_month_swap_in_place(self):
        assert "function navegar(href, empujar, quieto)" in _SCRIPT
        assert "destino.pathname !== location.pathname" in _SCRIPT
        assert "window.addEventListener('popstate'" in _SCRIPT

    def test_the_viewer_can_be_started_again_without_piling_up(self):
        assert "function iniciarVisor()" in _SCRIPT
        assert "visorControl.abort()" in _SCRIPT
        assert "observadorVisor.disconnect()" in _SCRIPT


class TestListSwitchOrder:
    def test_todas_comes_first(self):
        html_out = editor("2026", "SEPTIEMBRE", [], "t", {})
        modo = html_out[html_out.index('class="modo-hojas"'):]
        assert modo.index("Todas (") < modo.index("Por revisar (")


ELEC = "Electricidad y Alumbrado"
PARK = "Parking"
REF = "mant 02-09-2026 p1"


def maint(id_, text, block, ref=REF):
    return an_entry(id=id_, text=text, block=block, review_ref=ref, original_text=text)


def maint_editor(entries, **kw):
    kw.setdefault("tag_counts", {ELEC: 2, PARK: 1})
    return editor("2026", "SEPTIEMBRE", entries, "t", {}, section="mantenimiento", **kw)


class TestMantenimientoList:
    ENTRIES = [maint(1, "luz", ELEC), maint(2, "cargador", PARK), maint(3, "foco", ELEC)]

    def test_no_block_headings(self):
        assert "titulo-bloque" not in maint_editor(self.ENTRIES)

    def test_each_sheet_once(self):
        html = maint_editor(self.ENTRIES)
        assert html.count('class="cabecera-hoja') == 1

    def test_lines_in_the_order_given(self):
        html = maint_editor(self.ENTRIES)
        assert html.index(">luz<") < html.index(">cargador<") < html.index(">foco<")

    def test_seguridad_keeps_its_block_heading_and_has_no_chip(self):
        html = editor("2026", "SEPTIEMBRE", [an_entry()], "t", {})
        assert "titulo-bloque" in html
        assert "etiqueta-linea" not in html
        assert "filtro-etiquetas" not in html


class TestTagChip:
    def test_every_line_has_a_chip_naming_its_tag(self):
        html = maint_editor([maint(7, "cargador", PARK)])
        assert 'action="/entrada/7/bloque"' in html
        assert 'class="etiqueta etiqueta-parking"' in html
        assert f'title="{PARK}"' in html

    def test_the_menu_offers_all_four_tags_as_submit_buttons(self):
        html = maint_editor([maint(7, "cargador", PARK)])
        for slug in ("electricidad", "ascensores", "parking", "otros"):
            assert f'name="etiqueta" value="{slug}"' in html

    def test_the_current_tag_is_marked(self):
        html = maint_editor([maint(7, "cargador", PARK)])
        assert ('value="parking" class="opcion-etiqueta etiqueta-parking" '
                'aria-pressed="true"') in html

    def test_the_chip_form_carries_the_token_and_the_view(self):
        html = maint_editor([maint(7, "cargador", PARK)], tag_filter="parking")
        menu = html[html.index('action="/entrada/7/bloque"'):]
        menu = menu[:menu.index("</form>")]
        assert 'name="csrf" value="t"' in menu
        assert 'name="bloque" value="parking"' in menu
        assert 'name="seccion" value="mantenimiento"' in menu


class TestFilterBar:
    @staticmethod
    def document(html):
        """The centre panel only: the sidebar lists every sheet whatever the filter."""
        start = html.index('class="panel-documento"')
        return html[start:html.index('class="panel-imagen"', start)]

    def test_counts_for_the_whole_month(self):
        html = maint_editor(TestMantenimientoList.ENTRIES)
        assert 'Todas <span class="cuenta">3</span>' in html
        assert 'Electricidad <span class="cuenta">2</span>' in html
        assert 'Parking <span class="cuenta">1</span>' in html
        assert 'Otros <span class="cuenta">0</span>' in html

    def test_links_carry_the_slug(self):
        html = maint_editor(TestMantenimientoList.ENTRIES)
        assert 'href="/mantenimiento/2026/SEPTIEMBRE?bloque=parking"' in html

    def test_the_active_filter_is_not_a_link(self):
        html = maint_editor([maint(2, "cargador", PARK)], tag_filter="parking")
        assert 'aria-current="true">Parking' in html
        assert 'href="/mantenimiento/2026/SEPTIEMBRE"' in html, "Todas clears it"

    def test_a_filter_hides_empty_sheets(self):
        empty = "mant 03-09-2026 p2"
        html = maint_editor([maint(2, "cargador", PARK)], tag_filter="parking",
                            all_sheets={REF: 0, empty: 0})
        assert "03-09-2026" not in self.document(html)

    def test_without_a_filter_empty_sheets_are_shown(self):
        empty = "mant 03-09-2026 p2"
        html = maint_editor([maint(2, "cargador", PARK)], all_sheets={REF: 0, empty: 0})
        assert "03-09-2026" in self.document(html)

    def test_an_unknown_filter_is_never_echoed(self):
        html = maint_editor([maint(2, "cargador", PARK)], tag_filter="<script>")
        assert "<script>" not in html
        assert "&lt;script" not in html
        assert 'name="bloque"' not in html

    def test_an_empty_filtered_month_says_so_in_spanish(self):
        html = maint_editor([], tag_filter="otros", tag_counts={})
        assert "No hay anotaciones de este apartado en este mes." in html


def css_rule(selector):
    """The declarations of the first rule whose selector is exactly *selector*."""
    match = re.search(r"(?:^|\n)" + re.escape(selector) + r"\s*{([^}]*)}", STYLESHEET)
    assert match, selector
    return match.group(1)


class TestCompactRow:
    def test_the_tag_menu_opens_into_the_panel_above_everything(self):
        """It was anchored at its right edge from a chip in the 14px first
        column, so it opened left, under the sidebar, and could not be used."""
        menu = css_rule(".menu-etiquetas")
        assert "left: 0" in menu and "right: 0" not in menu
        assert "z-index: 20" in menu

    def test_the_chip_has_a_cell_of_its_own(self):
        assert "grid-area: etiqueta" in css_rule(".etiqueta-linea")
        assert "etiqueta" in css_rule(".fila-entrada.con-etiqueta")

    def test_a_maintenance_row_carries_its_tag_for_the_stripe(self):
        html = maint_editor([maint(7, "cargador", PARK)])
        assert 'class="fila-entrada con-etiqueta" id="entrada-7" data-etiqueta="parking"' in html
        assert "--etiqueta-parking" in css_rule('.fila-entrada[data-etiqueta="parking"]')

    def test_a_security_row_has_no_tag(self):
        html = editor("2026", "SEPTIEMBRE", [an_entry()], "t", {})
        assert "data-etiqueta" not in html and "con-etiqueta" not in html

    def test_an_unflagged_line_can_be_marked_for_review(self):
        html = editor("2026", "SEPTIEMBRE", [an_entry()], "t", {})
        assert 'name="accion" value="revisar"' in html

    def test_a_flagged_line_has_no_mark_button(self):
        html = editor("2026", "SEPTIEMBRE", [an_entry(flagged=1)], "t", {})
        assert 'value="revisar"' not in html

    def test_guardar_linea_shows_only_while_the_line_is_edited(self):
        assert "display: none" in css_rule(".forma-texto > .boton-icono")
        # The text's own form, not the row: focus anywhere in the row (the
        # tag chip) grew it between mousedown and mouseup, so the click
        # landed beside the chip and its menu never opened.
        shown = css_rule(".forma-texto:focus-within > .boton-icono,\n"
                         ".fila-entrada:has(.sin-guardar) .forma-texto > .boton-icono")
        assert "display: inline-block" in shown
        assert ".fila-entrada:focus-within" not in STYLESHEET

    def test_the_box_grows_with_its_text(self):
        assert "field-sizing: content" in css_rule(".texto-entrada")

    def test_eliminar_keeps_its_name_as_an_icon(self):
        html = editor("2026", "SEPTIEMBRE", [an_entry()], "t", {})
        boton = html[html.index('value="eliminar"'):]
        boton = boton[:boton.index("</button>")]
        assert 'aria-label="Eliminar"' in boton and 'title="Eliminar"' in boton
        assert '<span class="solo-lector">Eliminar</span>' in boton


class TestStickyFilterBar:
    def test_it_sticks_flush_to_the_top_of_the_document_panel(self):
        """top: 0 would stop it 16px down, under the panel's padding, with
        lines scrolling past in the gap above it."""
        barra = css_rule(".filtro-etiquetas")
        assert "position: sticky" in barra
        assert "top: -16px" in barra
        assert "background: var(--surface)" in barra, "lines pass under it, not through it"

    def test_it_sits_over_the_rows_but_under_an_open_tag_menu(self):
        barra = int(re.search(r"z-index: (\d+)", css_rule(".filtro-etiquetas")).group(1))
        menu = int(re.search(r"z-index: (\d+)", css_rule(".menu-etiquetas")).group(1))
        assert 0 < barra < menu

    def test_a_jump_lands_below_it(self):
        assert "--alto-filtro:" in STYLESHEET
        margen = css_rule(".entradas:has(.filtro-etiquetas) .cabecera-hoja,\n"
                          ".entradas:has(.filtro-etiquetas) .fila-entrada")
        assert "scroll-margin-top: calc(var(--alto-filtro) + 8px)" in margen

    def test_stacked_panels_scroll_without_padding_so_it_sticks_at_zero(self):
        estrecho = STYLESHEET[STYLESHEET.index("@media (max-width: 1100px)"):]
        estrecho = estrecho[:estrecho.index("\n}\n")]
        assert ".filtro-etiquetas { top: 0; }" in estrecho


class TestViewStateTravels:
    HOJA = "mant_02-09-2026_p1.jpg"

    def html(self, **kw):
        kw.setdefault("all_sheets", {REF: 0})
        return maint_editor([maint(2, "cargador", PARK)], selected_hoja=self.HOJA, **kw)

    def test_filter_chips_keep_the_open_sheet_and_the_shortlist(self):
        # With a filter on, so Todas is a link and not the current chip.
        html = self.html(showing_all=False, tag_filter="parking")
        assert (f'href="/mantenimiento/2026/SEPTIEMBRE?bloque=otros&hoja={self.HOJA}'
                '&hojas=pendientes"') in html
        assert f'href="/mantenimiento/2026/SEPTIEMBRE?hoja={self.HOJA}&hojas=pendientes"' in html

    def test_sheet_links_keep_the_filter(self):
        html = self.html(tag_filter="parking")
        heading = html[html.index('class="cabecera-hoja'):]
        assert "&bloque=parking#" in heading[:heading.index(">")]
        lista = html[html.index('class="lista-hojas"'):]
        assert "&bloque=parking#" in lista[:lista.index("</ul>")]
        assert "hojas=pendientes&hoja=" in html and "&bloque=parking\"" in html

    def test_no_filter_adds_nothing(self):
        assert "bloque=" not in self.html().split('class="filtro-etiquetas"')[0]
