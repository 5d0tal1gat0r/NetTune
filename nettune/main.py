"""Entry point: watch for printer scans, transcribe them, file the report."""

import contextlib
import json
import logging
import os
import shutil
import sqlite3
import tempfile
import time
from datetime import datetime, timedelta, timezone
from logging.handlers import TimedRotatingFileHandler

from nettune.config import config
from nettune.dates.batch_dates import (
    batch_month,
    batch_summary,
    chronological_order,
    date_pages_by_position,
    filing_months,
    reconcile_batch,
)
from nettune.intake.pdf_pages import PdfRenderError, is_pdf, render_pages
from nettune.intake.processed_ledger import ProcessedLedger
from nettune.intake.retry_scheduler import RetryScheduler
from nettune.intake.scan_filter import is_processable_scan, iter_pending_scans
from nettune.intake.scanner_monitor import ScannerMonitor, wait_for_file_stable
from nettune.ops import nettune_feedback
from nettune.ops.notify import Notifier
from nettune.ops.notify import enabled as notify_enabled
from nettune.ops.spend_guard import BudgetExceeded, OutOfCredit, SpendGuard
from nettune.pages.document_type import SEGURIDAD
from nettune.pages.page_kind import MANTENIMIENTO, PARKING, classify
from nettune.pages.page_rotation import rotate_by, straighten, to_portrait
from nettune.pages.same_paper import already_read
from nettune.pages.sheet_split import split_sheets
from nettune.reading.filtering_agents import filter_page
from nettune.reading.page_reader import read_page_with_consensus
from nettune.reading.transcription_service import TranscriptionError
from nettune.report.entry_store import EntryStore, review_line
from nettune.report.memoria import MANTENIMIENTO_BLOCKS, SEGURIDAD_BLOCK, fill_memoria
from nettune.report.memoria_blocks import OTROS
from nettune.report.month_folders import (
    DUPLICATES_DIR_NAME,
    MONTH_FOLDERS,
    PARKING_DIR_NAME,
    REVISION_DIR_NAME,
    archive_dir_for,
    ensure_month_tree,
    get_month_folder,
    get_year_folder,
    is_year,
    memoria_name,
    month_dir_for,
    parking_dir_for,
    processed_dir_for,
    revision_dir_for,
)
from nettune.report.review_marks import image_name, is_maintenance_ref, locator, needs_review

os.makedirs("logs", exist_ok=True)

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        TimedRotatingFileHandler(
            "logs/security_processor.log", when="midnight", interval=1
        ),
        logging.StreamHandler(),
    ],
)


def post_process_text(text: str) -> str:
    """Basic post-processing to clean up extracted text."""
    if not text:
        return ""
    return "\n".join([line.strip() for line in text.split("\n") if line.strip()])


def unique_destination(directory: str, filename: str) -> str:
    """A free path in *directory*, suffixing "_1", "_2"... on collision."""
    stem, extension = os.path.splitext(filename)
    candidate = os.path.join(directory, filename)
    counter = 1
    while os.path.exists(candidate):
        candidate = os.path.join(directory, f"{stem}_{counter}{extension}")
        counter += 1
    return candidate


def archive_scan(scan_path: str, year: str, month: str) -> str:
    """Move a processed scan into its month's archive folder."""
    archive_dir = archive_dir_for(config.incoming_dir, year, month)
    os.makedirs(archive_dir, exist_ok=True)
    destination = unique_destination(archive_dir, os.path.basename(scan_path))
    shutil.move(scan_path, destination)
    return destination


def parking_pages(workdir: str) -> list[str]:
    """The parking-ticket pages page_images set aside in *workdir*, in order."""
    folder = os.path.join(workdir, PARKING_PAGES)
    if not os.path.isdir(folder):
        return []
    return [os.path.join(folder, name) for name in sorted(os.listdir(folder))]


# Where page_images leaves the parking-ticket pages it takes out of a scan.
PARKING_PAGES = "parking"


def page_images(scan_path: str, workdir: str) -> list[str]:
    """Every sheet of a scan as an image, in reading order.

    PDFs are rasterised, images pass through, and each page is then told
    apart by its printed form (page_kind). Parking-ticket pages are taken out
    and left in workdir's PARKING_PAGES folder, for parking_pages to find;
    they are never read. A maintenance page is one sheet and stays whole.
    Every other page is split into the sheets printed on it: the scanner puts
    two daily security reports on every page. Splitting comes before
    straightening because the two sheets of a portrait page are rotated
    ninety degrees in opposite directions, so no single rotation is right for
    the page as a whole.
    """
    if is_pdf(scan_path):
        pages = render_pages(scan_path, workdir, dpi=config.pdf_dpi)
    else:
        pages = [scan_path]

    kinds = [classify(page) if config.classify_pages else "" for page in pages]
    set_aside = [page for page, kind in zip(pages, kinds, strict=True) if kind == PARKING]
    if set_aside:
        folder = os.path.join(workdir, PARKING_PAGES)
        os.makedirs(folder, exist_ok=True)
        for number, page in enumerate(set_aside, start=1):
            shutil.copy(page, os.path.join(folder, f"{number:03d}{os.path.splitext(page)[1]}"))
        logging.warning(f"{os.path.basename(scan_path)}: {len(set_aside)} of "
                        f"{len(pages)} page(s) are the parking-ticket log")
    whole = {page for page, kind in zip(pages, kinds, strict=True) if kind == MANTENIMIENTO}
    pages = [page for page, kind in zip(pages, kinds, strict=True) if kind != PARKING]

    if config.split_sheets:
        sheets = []
        for page in pages:
            if page in whole:
                sheets.append(page)
            else:
                sheets.extend(split_sheets(page, os.path.join(workdir, "hojas")))
        if len(sheets) != len(pages):
            logging.warning(
                f"{os.path.basename(scan_path)}: {len(pages)} page(s) hold "
                f"{len(sheets)} sheet(s)"
            )
        pages = sheets

    if config.auto_rotate:
        # Security sheets arrive sideways; a rotated sheet transcribes badly.
        # Aspect ratio settles landscape-vs-portrait with certainty -- every
        # sheet here is one split, A4-shaped page -- before OSD's guesswork
        # is asked to find the remaining upside-down turns. only_upside_down
        # keeps that guesswork from undoing the aspect-ratio correction: OSD
        # once read a false 270 on a sheet to_portrait had just fixed, and
        # without this the page went sideways again with nothing left to
        # notice.
        pages = [straighten(to_portrait(p), only_upside_down=True) for p in pages]
    return pages


def save_as_pdf(images: list[str], destination: str) -> None:
    """Put *images* into one PDF at *destination*, a page each."""
    from PIL import Image

    opened = [Image.open(path).convert("RGB") for path in images]
    try:
        opened[0].save(destination, save_all=True, append_images=opened[1:],
                       resolution=config.pdf_dpi)
    finally:
        for image in opened:
            image.close()
    with contextlib.suppress(OSError):
        os.chmod(destination, 0o666)


def date_security_pages_by_position(readings: list[dict], per_day: int) -> list[dict]:
    """date_pages_by_position over the security sheets, the rest untouched."""
    security = [i for i, page in enumerate(readings) if page.get("tipo") != MANTENIMIENTO]
    if len(security) == len(readings):
        return date_pages_by_position(readings, per_day)
    dated = date_pages_by_position([readings[i] for i in security], per_day)
    result = list(readings)
    for i, page in zip(security, dated, strict=True):
        result[i] = page
    return result


def save_review_image(image_path: str, mark_text: str, revision_dir: str,
                      hand_turn: int = 0) -> str:
    """Copy a page a human has to check into the month's review folder.

    Named exactly as the locator in the memoria reads, so there is nothing to
    look up: the entry says [22-06-2026 p2] and the file is 22-06-2026_p2.jpg.
    The copy is a convenience; failing to make one must never cost the month
    its memoria, so any error is reported and swallowed.

    *hand_turn* is how far a person already turned this sheet in the
    dashboard. The copy is written fresh, so without re-applying it a
    re-dropped scan would put a sheet somebody straightened back on its side.
    """
    try:
        os.makedirs(revision_dir, exist_ok=True)
        destination = os.path.join(revision_dir, image_name(mark_text))
        # Overwrite rather than uniquify: the same page re-dropped is the same
        # page, and a revision folder of near-duplicates helps nobody.
        shutil.copyfile(image_path, destination)
        if hand_turn:
            rotate_by(destination, hand_turn)
        return destination
    except OSError as exc:
        logging.warning(f"Could not save {mark_text} for review: {exc}")
        return ""


def blank_page_report(blank: list[int], total: int, source_name: str) -> str | None:
    """What to say about pages that produced no entry, or None if there were none.

    Such a page used to be skipped in silence unless *every* page was blank.
    Measured on a real 29 page batch: two pages produced no entry at all, and
    one was a legible printed list of pending works. Nobody was told. Naming
    them is the difference between a page the sheet genuinely left empty and a
    page that was lost.
    """
    if not blank:
        return None
    numbers = ", ".join(str(number) for number in blank)
    return (
        f"{source_name}: no entry read from page(s) {numbers} of {total}; "
        "check them by hand"
    )


def kept_corrections_report(kept: int, year: str, month: str) -> str | None:
    """What to say about corrections a reprocess did not touch, or None.

    Silence here would be the system appearing to ignore somebody's work.
    """
    if not kept:
        return None
    noun = "corrección" if kept == 1 else "correcciones"
    return (
        f"{year}/{month}: se conservan {kept} {noun} hechas a mano; "
        "no se han vuelto a leer"
    )


def _months_to_compare(year: str, month: str) -> list[str]:
    """Review folders a new scan may repeat: its folder's month, this month
    and last month."""
    today = datetime.now(timezone.utc)
    last = (today.replace(day=1) - timedelta(days=1))
    months = [(year, month)] if year and month else []
    months += [(str(d.year), MONTH_FOLDERS[d.month - 1]) for d in (today, last)]
    return list(dict.fromkeys(revision_dir_for(config.incoming_dir, y, m) for y, m in months))


def _filed_as(month_dir: str) -> str:
    """"2026/SEPTIEMBRE": how the ledger records where a scan was filed."""
    relative = os.path.relpath(month_dir, config.incoming_dir)
    return relative.replace(os.sep, "/")


def number_lines(lines: list[dict]) -> list[dict]:
    """Mark each line with its place on the page, as "orden".

    Done before a maintenance page is split under the memoria's four
    subheadings: after the split each line only knows its place within its
    own subheading, and the dashboard shows the sheet as it was written.
    """
    for index, entry in enumerate(lines):
        entry["orden"] = index
    return lines


def split_by_block(lines: list[dict]) -> dict[str, list[dict]]:
    """A maintenance page's lines under the subheadings they belong to.

    In the memoria's order, leaving out subheadings with no lines. A line
    with no "bloque" goes to Otros, the author's own catch-all.
    """
    return {
        block: chosen
        for block in MANTENIMIENTO_BLOCKS
        if (chosen := [t for t in lines if t.get("bloque", OTROS) == block])
    }


def process_scan(scan_path: str, ledger: ProcessedLedger, guard: SpendGuard,
                 store: EntryStore, digest: str | None = None,
                 filed: list | None = None) -> str:
    """Read every page of a scan and file its sheets for review.

    A month arrives as several scans: a batch of security sheets and one
    maintenance PDF. Each drop adds to the same month in the dashboard; the
    memoria itself is written from there once every sheet has been checked.
    The (year, month) pairs the sheets went to are appended to *filed*.

    Returns "processed", "duplicate-paper", "parking" when every page is the
    parking-ticket log, or "blank" when nothing legible
    was found. Raises on failure so the caller can schedule a retry.
    """
    if digest is None:
        digest = ledger.digest(scan_path)

    # Either folder may be missing: the colleague drops a batch wherever is
    # convenient, and the sheets themselves say where it belongs. Both are
    # settled from the dates once the pages have been read.
    year = get_year_folder(scan_path, config.incoming_dir)
    month = get_month_folder(scan_path, config.incoming_dir)

    start_time = time.time()
    source_name = os.path.basename(scan_path)

    with tempfile.TemporaryDirectory(prefix="scanpages_") as workdir:
        try:
            pages = page_images(scan_path, workdir)
        except PdfRenderError as exc:
            raise TranscriptionError(str(exc)) from exc

        # The parking-ticket log is kept, not read: beside the year folders,
        # as the whole file when that is all the scan held.
        parking = parking_pages(workdir)
        if parking:
            destination_dir = parking_dir_for(config.incoming_dir)
            os.makedirs(destination_dir, exist_ok=True)
            if not pages:
                destination = unique_destination(destination_dir, source_name)
                shutil.move(scan_path, destination)
                ledger.mark_processed(destination, PARKING_DIR_NAME, digest=digest)
                logging.warning(f"{source_name}: parking-ticket log, not read; "
                                f"moved to {destination}")
                return "parking"
            stem = os.path.splitext(source_name)[0]
            destination = unique_destination(destination_dir, f"{stem}_parking.pdf")
            save_as_pdf(parking, destination)
            logging.warning(f"{source_name}: {len(parking)} parking-ticket page(s) "
                            f"saved to {destination}; the rest is read")

        # A re-scan of paper already read is set aside before a single call
        # is paid for. Compared with the folder's month when it names one,
        # and with this month and the last, where a batch dropped anywhere
        # most likely belongs.
        matches = already_read(pages, _months_to_compare(year, month))
        if matches:
            pairs = ", ".join(f"{os.path.basename(existing)} ({score:.2f})"
                              for _, existing, score in matches)
            # Beside the month the matching sheets were filed in.
            month_dir = os.path.dirname(os.path.dirname(matches[0][1]))
            destination_dir = os.path.join(month_dir, DUPLICATES_DIR_NAME)
            os.makedirs(destination_dir, exist_ok=True)
            destination = unique_destination(destination_dir, source_name)
            shutil.move(scan_path, destination)
            ledger.mark_processed(destination, _filed_as(month_dir), digest=digest)
            logging.warning(
                f"{source_name}: every sheet is paper already read ({pairs}); "
                f"not read again, moved to {destination}"
            )
            return "duplicate-paper"

        logging.warning(f"{source_name}: {len(pages)} page(s) to read")
        readings = []
        # ocr_feedback: every stage of every sheet, kept beside the work and
        # never in its way (nettune_feedback never raises).
        run_id = nettune_feedback.start_run(source_name)
        captured = {}

        for number, image in enumerate(pages, start=1):
            cache_key = f"page:{number}"
            cached = ledger.cache_get(digest, cache_key)
            if cached:
                page = json.loads(cached)
                captured[number] = (None, nettune_feedback.snapshot(page), True)
                logging.warning(f"Page {number}/{len(pages)}: reusing earlier reading")
            else:
                logging.warning(f"Page {number}/{len(pages)}: reading "
                                f"{config.readings_per_page}x ({guard.summary()})")
                passes = []
                page = read_page_with_consensus(
                    image, guard=guard, readings=config.readings_per_page,
                    collector=passes,
                )
                ledger.cache_put(digest, cache_key, json.dumps(page, ensure_ascii=False))
                nettune_feedback.record_passes(run_id, source_name, number, passes)
                captured[number] = (passes, nettune_feedback.snapshot(page), False)
            readings.append(page)

        # A batch is one scanning session covering contiguous days, so a page
        # dated far from its neighbours has been misread even when every
        # reading pass agreed on it. Costs nothing and catches what consensus
        # cannot.
        readings = reconcile_batch(readings)
        # And the sheets come a fixed number to a day, in order, which says
        # more about a sheet's day than the model's reading of it: on
        # September's batch position was right every time the paper was
        # checked, the read date a third of the time wrong.
        # Security sheets only: maintenance is one sheet a working day, with
        # weekends and holidays missing, so its place in the batch says
        # nothing about its day.
        if config.sheets_per_day:
            readings = date_security_pages_by_position(readings, config.sheets_per_day)

        # The sheets say where the batch belongs, wherever it was dropped:
        # the top of the share, a year folder, or the wrong month's folder.
        # The folder only decides when too few dates could be read.
        by_dates = batch_month(readings, max(2, config.sheets_per_day))
        if by_dates and by_dates != (year, month):
            if year and month:
                logging.warning(f"{source_name}: dropped in {year}/{month} but its sheets "
                                f"are from {by_dates[0]}/{by_dates[1]}; filed there")
            else:
                logging.warning(f"{source_name}: filing under {by_dates[0]}/{by_dates[1]} "
                                "by its dates")
            year, month = by_dates
        elif not year or not month:
            where = "/".join(p for p in (year, month) if p) or "the share root"
            raise TranscriptionError(
                f"{source_name} is in {where} and no date on it could be read; "
                "move it into the right year and month by hand"
            )

        # Stage 2: tidy the wording and redact names. Runs once per page on
        # text the reading passes already agreed on, so it is nearly free and
        # cannot disturb the consensus flags.
        if config.enable_filter_stage:
            readings = [filter_page(page, guard=guard) for page in readings]
        # ocr_feedback: the filter's output as it left the filter, before the
        # review marks below touch the entries.
        filtered_snapshots = [nettune_feedback.snapshot(p) for p in readings]
        logging.warning(f"{source_name}: fechas {batch_summary(readings)}")

        added_total, blank = 0, []

        # Numbered in the order the shifts happened, not the order the sheets
        # went through the scanner, so p1 is a day's first shift and p4 its
        # last. The scan position is kept beside it.
        # A scan with nothing legible on any page is left where it is,
        # untouched. Otherwise every sheet is kept -- a blank one too: the
        # model finding nothing on it does not mean nothing is written there,
        # and a person must be able to open it and add what is.
        all_blank = not any(page.get("trabajos") for page in readings)
        folders = filing_months(readings, year, month, max(2, config.sheets_per_day))
        touched = []
        # Seguridad and Mantenimiento each number their sheets on their own,
        # in date order: the month's first maintenance sheet is p1 whatever
        # the security sheets are. Each carries on from the pages other scans
        # of its section already use in the months this one files into.
        numbers = {
            maintenance: max((store.last_page(y, m, excluding=source_name,
                                              maintenance=maintenance)
                              for y, m in set(folders)), default=0)
            for maintenance in (False, True)
        }

        # In the order the paper was scanned, a day's shifts put in time order.
        # Not re-sorted by the date read: the maintenance stack comes day by
        # day, and September's had two misread dates (31-07 for the first
        # sheet, 13-09 for the fourth) that sorting would have moved out of
        # place. A wrong date is corrected in the dashboard, which keeps pN.
        for index in chronological_order(readings):
            page = readings[index]
            maintenance = page.get("tipo") == MANTENIMIENTO
            numbers[maintenance] += 1
            number = numbers[maintenance]
            # Each sheet in its own month's memoria: a batch can run over
            # the end of the month it was dropped in.
            sheet_year, sheet_month = folders[index]
            if (sheet_year, sheet_month) not in touched:
                touched.append((sheet_year, sheet_month))
            is_blank = not page.get("trabajos")
            if is_blank:
                blank.append(number)
                if all_blank:
                    continue

            visible = [
                t for t in (page.get("trabajos") or [])
                if not (config.omit_routine and t.get("routine"))
            ]

            # Point the reader at the page behind an entry nobody should trust
            # as it stands. The same locator names the entry in the memoria
            # and the image in the revision folder.
            page_ref = ""
            if config.mark_uncertain:
                page_ref = locator(page.get("fecha"), number, source_name,
                                   maintenance=maintenance)
                doubtful = 0
                for entry in visible:
                    if needs_review(entry, page):
                        entry["confident"] = False
                        doubtful += 1
                # Every page, not only the ones with a doubtful line. The
                # flags are a shortlist, not a guarantee, and someone who
                # wants to read the whole batch against the paper needs the
                # clean sheets to be there too. One JPEG per sheet.
                save_review_image(
                    pages[index], page_ref,
                    revision_dir_for(config.incoming_dir, sheet_year, sheet_month),
                    hand_turn=store.hand_turn(image_name(page_ref)),
                )
                # Recorded whether or not any line ends up pointing at it,
                # so every sheet of the batch can be opened and offered.
                store.record_sheet(sheet_year, sheet_month, source_name, number, page_ref,
                                   scan_position=index + 1)
                if doubtful:
                    logging.warning(
                        f"{source_name}: {doubtful} entry(ies) on page {number} "
                        f"need checking; saved as {image_name(page_ref)}"
                    )

            _, consensus, was_cached = captured.get(index + 1, (None, None, False))
            nettune_feedback.record_sheet(
                run_id, source_name, index + 1, page_ref,
                image_name(page_ref) if page_ref else "",
                "mantenimiento" if maintenance else "seguridad",
                consensus, filtered_snapshots[index], config.omit_routine, was_cached,
            )

            if is_blank:
                continue
            number_lines(visible)
            if page.get("tipo") == SEGURIDAD:
                added_total += store.add(
                    sheet_year, sheet_month, SEGURIDAD_BLOCK, visible, source_name, page_ref
                )
            else:
                # Maintenance entries are split across the memoria's four
                # fixed subheadings; each keeps its place on the page.
                for block, chosen in split_by_block(visible).items():
                    added_total += store.add(
                        sheet_year, sheet_month, block, chosen, source_name, page_ref
                    )

    if len(blank) == len(pages):
        logging.error(f"No legible content on any page of {scan_path}; left in place")
        return "blank"

    report = blank_page_report(blank, len(pages), source_name)
    if report:
        logging.error(report)

    # No document yet: the memoria is written from the dashboard, once a
    # person has been through every sheet (see the dashboard's Guardar).
    # Except that a final one written before these sheets came in is not
    # final any more, and on the share it would look like the month is done.
    for sheet_year, sheet_month in touched:
        retire_stale_final(store, sheet_year, sheet_month)
    for other in touched:
        if other != (year, month):
            logging.warning(f"{source_name}: sheets dated {other[1]} {other[0]} filed there")
    if filed is not None:
        filed.extend(touched)
    ledger.mark_processed(scan_path, f"{year}/{month}", digest=digest)
    ledger.clear_cache(digest)
    archived = archive_scan(scan_path, year, month)

    counts = store.counts(year, month)
    logging.warning(
        f"--- {source_name}: {len(pages)} page(s), {added_total} new entry(ies), "
        f"{sum(counts.values())} total in {year}/{month} "
        f"({store.flagged_count(year, month)} flagged), "
        f"{time.time() - start_time:.1f}s. Ready for review in the dashboard. "
        f"Archived to {archived}. {guard.summary()} ---\n"
    )
    return "processed"


def rebuild_memoria(store: EntryStore, year: str, month: str, draft: bool = False) -> str:
    """Regenerate the month's memoria from every entry gathered so far.

    The sheets worth a second look are listed once each at the end of the
    security block, naming the image in the revision folder. Marking every
    doubtful entry inline was tried first and abandoned: on a real batch four
    entries in five came back doubtful, and a marker that common is ignored.

    A *draft* is written under the draft's name. Only one of the two is left
    in the month folder: a final written before later sheets came in would
    otherwise sit beside the draft looking current.
    """
    out_dir = processed_dir_for(config.incoming_dir, year, month)
    out_path = os.path.join(out_dir, memoria_name(year, month, draft=draft))
    other = os.path.join(out_dir, memoria_name(year, month, draft=not draft))

    seguridad = store.entries(year, month, SEGURIDAD_BLOCK)
    mantenimiento = {block: store.entries(year, month, block) for block in MANTENIMIENTO_BLOCKS}
    if config.mark_uncertain:
        pages = store.review_pages(year, month)
        if pages:
            # Each section's sheets listed in its own part of the memoria:
            # security ones after the security block, maintenance ones at
            # the end of the maintenance section.
            seguridad = seguridad + [
                review_line(ref, count) for ref, count in pages.items()
                if not is_maintenance_ref(ref)
            ]
            mantenimiento[OTROS] = mantenimiento[OTROS] + [
                review_line(ref, count) for ref, count in pages.items()
                if is_maintenance_ref(ref)
            ]
            logging.warning(
                f"{year}/{month}: {len(pages)} sheet(s) to check by hand; "
                f"the images are in {REVISION_DIR_NAME}/"
            )

    fill_memoria(
        config.template_path, out_path, mantenimiento, seguridad,
        monthly=(config.incoming_dir, year, month),
    )
    with contextlib.suppress(FileNotFoundError):
        os.remove(other)
    return out_path


def retire_stale_final(store: EntryStore, year: str, month: str) -> None:
    """Turn the month's final memoria back into the draft when sheets are
    left to check.

    The draft is written afresh, so it carries the new lines too. Should that
    fail, the final is renamed to the draft's name as it stands: old text
    under the draft's name is better than a document that says it is
    finished when it is not.
    """
    folder = processed_dir_for(config.incoming_dir, year, month)
    final = os.path.join(folder, memoria_name(year, month))
    if not os.path.exists(final) or not store.to_check(year, month):
        return
    try:
        rebuild_memoria(store, year, month, draft=True)
    except Exception as exc:
        logging.error(f"{year}/{month}: could not write the draft ({exc}); "
                      f"the final memoria is renamed to the draft instead")
        os.replace(final, os.path.join(folder, memoria_name(year, month, draft=True)))
        return
    logging.warning(f"{year}/{month}: new sheets to check, the final memoria "
                    f"is the draft again")


def wait_until_ready(scan_path: str) -> bool:
    """Retry the stability check a few times before giving up on a scan."""
    max_retries = 3
    for attempt in range(1, max_retries + 1):
        if wait_for_file_stable(scan_path, timeout=config.stability_timeout):
            return True
        logging.warning(f"File not stable, attempt {attempt}/{max_retries}")
    logging.error(
        f"File stability check failed after {max_retries} attempts: {scan_path}"
    )
    return False


def handle_candidate(
    scan_path: str,
    ledger: ProcessedLedger,
    retries: RetryScheduler,
    monitor: ScannerMonitor,
    guard: SpendGuard,
    store: EntryStore,
    notifier: Notifier | None = None,
) -> str:
    """Handle one dequeued path and return the outcome.

    Every exit resolves the retry scheduler. A branch that returns without
    calling record_failure or forget would strand the scan: due() has already
    parked it, so it would never be retried, abandoned, or logged again.
    """

    def release(outcome: str) -> str:
        retries.forget(scan_path)
        monitor.forget(scan_path)
        return outcome

    def reschedule(outcome: str) -> str:
        retries.record_failure(scan_path)
        monitor.forget(scan_path)
        return outcome

    if not is_processable_scan(scan_path, config.incoming_dir, warn=True):
        return release("ignored")

    if not wait_until_ready(scan_path):
        if not os.path.exists(scan_path):
            logging.warning(f"Scan disappeared before it settled: {scan_path}")
            return release("vanished")
        return reschedule("unstable")

    logging.warning(f"\n--- New scan detected: {scan_path} ---")

    try:
        digest = ledger.digest(scan_path)
        if ledger.already_processed(scan_path, digest=digest):
            # The same file again, wherever it was dropped: set it beside the
            # month it was filed in, not read and not costing anything.
            filed = ledger.filed_as(digest)
            parts = filed.split("/")
            if len(parts) == 2 and is_year(parts[0]) and parts[1] in MONTH_FOLDERS:
                where = os.path.join(month_dir_for(config.incoming_dir, *parts),
                                     DUPLICATES_DIR_NAME)
                os.makedirs(where, exist_ok=True)
                shutil.move(scan_path, unique_destination(where, os.path.basename(scan_path)))
            else:
                where = archive_scan(scan_path,
                                     get_year_folder(scan_path, config.incoming_dir),
                                     get_month_folder(scan_path, config.incoming_dir))
            logging.warning(f"Already processed identical scan, moved to {where}")
            if notifier:
                notifier.already_read(os.path.basename(scan_path))
            return release("duplicate")
    except (sqlite3.Error, OSError) as exc:
        logging.error(f"Could not check the ledger for {scan_path}: {exc}")
        return reschedule("error")

    filed: list = []
    name = os.path.basename(scan_path)
    if notifier:
        notifier.busy()
    try:
        outcome = process_scan(scan_path, ledger, guard, store, digest=digest, filed=filed)
    except OutOfCredit as exc:
        # The account, not the monthly cap: it can be topped up any time, so
        # the scan waits for a restart or for being dropped again.
        logging.error(str(exc))
        if notifier:
            notifier.problem(name, "la cuenta de OpenAI se ha quedado sin saldo. Recárguela "
                                   "y vuelva a dejar el archivo, o reinicie el servicio.")
        return release("out-of-credit")
    except BudgetExceeded as exc:
        # Not a transient fault: stop retrying until the month rolls over.
        logging.error(str(exc))
        if notifier:
            notifier.problem(name, "se ha agotado el presupuesto mensual de lectura. "
                                   "Se leerá automáticamente a principios del mes que viene.")
        return release("over-budget")
    except TranscriptionError as exc:
        logging.error(f"Transcription failed for {scan_path}: {exc}")
        return reschedule("error")
    except Exception as exc:
        logging.exception(f"Error processing {scan_path}: {exc}")
        return reschedule("error")

    if outcome == "blank":
        # A blank page is a real answer, not a transient fault: retrying it
        # would just pay for the same empty result again.
        if notifier:
            notifier.problem(name, "no se ha encontrado nada legible en ninguna página.")
        return release("blank")
    if outcome == "parking":
        return release("parking")
    if outcome == "duplicate-paper":
        if notifier:
            notifier.already_read(name)
        return release("duplicate-paper")
    if notifier:
        notifier.filed(filed)
    return release("processed")


def _utc_month() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def start_of_month(monitor, incoming_dir: str) -> int:
    """What a new month needs, without a restart. Returns scans re-queued.

    The folders for the year now current and the next are laid out, so the
    first scan of January has somewhere to go. And every scan still waiting
    in the share is offered again: one held back because the month's budget
    ran out stays there, and the budget it was waiting for has just reset.
    """
    ensure_month_tree(incoming_dir)
    waiting = list(iter_pending_scans(incoming_dir))
    for path in waiting:
        monitor.enqueue(path)
    if waiting:
        logging.warning(f"New month: offering {len(waiting)} waiting scan(s) again")
    return len(waiting)


def main():
    logging.warning("Starting Security Log Processing App...")

    ensure_month_tree(config.incoming_dir)

    monitor = ScannerMonitor(
        config.incoming_dir,
        mode=config.watch_mode,
        poll_interval=config.poll_interval,
    )
    monitor.start()

    # Pick up anything that arrived while the service was stopped.
    backlog = list(iter_pending_scans(config.incoming_dir))
    if backlog:
        logging.warning(f"Found {len(backlog)} scan(s) waiting from a previous run")
        for pending in backlog:
            monitor.enqueue(pending)

    logging.warning(f"Listening for new printer scans in: {config.incoming_dir}")
    logging.warning("Press Ctrl+C to stop.")

    ledger = ProcessedLedger(config.state_db)
    store = EntryStore(config.entry_db)
    guard = SpendGuard(
        config.spend_db,
        monthly_budget_eur=config.monthly_budget_eur,
        eur_usd=config.eur_usd,
    )
    logging.warning(
        f"Model {config.model_name}, {config.readings_per_page} reading(s)/page, "
        f"{config.pdf_dpi} dpi. {guard.summary()}"
    )
    retries = RetryScheduler(
        base_delay=config.retry_base_delay,
        max_attempts=config.retry_max_attempts,
    )
    notifier = Notifier(store)
    if not notify_enabled():
        logging.warning("Email not configured (NOTIFY_TO, SMTP_HOST): no notices will be sent")
    # The spend guard counts its months in UTC, so the new month starts
    # when its budget does, not at local midnight two hours earlier.
    this_month = _utc_month()
    try:
        while True:
            scan_path = monitor.get_new_file(timeout=1)

            if not scan_path:
                if _utc_month() != this_month:
                    this_month = _utc_month()
                    start_of_month(monitor, config.incoming_dir)
                # Nothing new: re-attempt anything that failed earlier.
                for path in retries.due():
                    if os.path.exists(path):
                        logging.warning(f"Retrying previously failed scan: {path}")
                        monitor.enqueue(path)
                    else:
                        retries.forget(path)
                if guard.warn_if_low() and notifier:
                    notifier.budget_low(guard.summary())
                for path in retries.abandoned[:]:
                    logging.error(
                        f"Giving up on {path} after {config.retry_max_attempts} "
                        "attempts; it stays in the incoming folder for manual review"
                    )
                    notifier.problem(
                        os.path.basename(path),
                        f"ha fallado {config.retry_max_attempts} veces seguidas (por ejemplo, "
                        "no se pudo leer ninguna fecha, o el servicio de lectura no "
                        "respondía). Muévalo a la carpeta de su mes, o avise al "
                        "administrador.")
                    retries.abandoned.remove(path)
                notifier.tick()
                continue

            handle_candidate(scan_path, ledger, retries, monitor, guard, store, notifier)

    except KeyboardInterrupt:
        logging.warning("\nShutting down service...")
    finally:
        logging.warning(guard.summary())
        guard.close()
        store.close()
        ledger.close()
        monitor.stop()


if __name__ == "__main__":
    main()
