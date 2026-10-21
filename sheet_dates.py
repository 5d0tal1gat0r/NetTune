"""Changing a sheet's date: the store, the image file and the hand turn together.

A sheet's date is spelled into its reference and its image's file name, and
both have to move at once or the dashboard shows one sheet's lines beside
another's picture. The dashboard's date control and tools/date_by_position.py
both come through here.
"""

import logging
import os

from entry_store import EntryStore
from review_marks import image_name, plain_ref, same_kind


def set_sheet_date(store: EntryStore, year: str, month: str, review_ref: str,
                   new_date: str, revision_dir: str, *, confirm_only: bool = False
                   ) -> tuple[str | None, str]:
    """Give a sheet *new_date* (DD-MM-YYYY). Returns (new reference, error).

    On any refusal the store and the folder are left exactly as they were.
    *confirm_only* keeps the date and only marks it checked.
    """
    identity = store.sheet_identity(year, month, review_ref)
    if identity is None:
        return None, "No se encuentra la hoja"
    source, page = identity
    if confirm_only:
        new_date = plain_ref(review_ref).split(" ")[0]
    new_ref = same_kind(f"{new_date} p{page}", review_ref)
    old_name, new_name = image_name(review_ref), image_name(new_ref)
    old_path = os.path.join(revision_dir, old_name)
    new_path = os.path.join(revision_dir, new_name)

    # Checked before anything is written.
    if new_name != old_name and os.path.exists(new_path):
        return None, "Ya hay otra hoja con esa fecha y ese número de página"
    if store.redate_sheet(year, month, review_ref, new_date) is None:
        return None, f"Fecha no válida: tiene que ser un día de {month.lower()} de {year}"
    if new_name != old_name and os.path.exists(old_path):
        try:
            os.rename(old_path, new_path)
        except OSError as exc:
            store.restore_sheet_ref(year, month, source, page, new_ref, review_ref)
            logging.error(f"No se pudo renombrar {old_path}: {exc}")
            return None, "No se pudo renombrar la imagen de la hoja"
    if new_name != old_name:
        store.rename_turn(old_name, new_name)
    return new_ref, ""


def renumber_files(store: EntryStore, revision_dir: str,
                   pairs: list[tuple[str, str]]) -> None:
    """Rename the images (and their hand turns) of renumbered sheets.

    *pairs* comes from EntryStore.renumber_sheets. Renumbering is usually a
    swap -- 01-09-2026_p1 and _p2 trade names -- so every file first goes to
    a temporary name, and only then to its new one.
    """
    staged = []
    for i, (old_ref, new_ref) in enumerate(pairs):
        old_name, new_name = image_name(old_ref), image_name(new_ref)
        temporary = f".renumbering-{i}{os.path.splitext(old_name)[1]}"
        if os.path.exists(os.path.join(revision_dir, old_name)):
            os.rename(os.path.join(revision_dir, old_name),
                      os.path.join(revision_dir, temporary))
        store.rename_turn(old_name, temporary)
        staged.append((temporary, new_name))
    for temporary, new_name in staged:
        if os.path.exists(os.path.join(revision_dir, temporary)):
            os.rename(os.path.join(revision_dir, temporary),
                      os.path.join(revision_dir, new_name))
        store.rename_turn(temporary, new_name)
