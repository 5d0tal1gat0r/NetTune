"""A re-scan of paper already read is set aside before it is paid for."""

import os

import pytest
from PIL import Image, ImageDraw

from same_paper import MATCH, already_read, signature, similarity


def _sheet(path, seed, noise=0):
    """A form: header, ruled box, and handwriting that differs by *seed*."""
    import random
    rng = random.Random(seed)
    image = Image.new("L", (600, 850), 255)
    draw = ImageDraw.Draw(image)
    draw.rectangle((40, 30, 560, 140), outline=0, width=3)
    draw.rectangle((40, 170, 560, 700), outline=0, width=3)
    for _ in range(90):
        x, y = rng.randint(60, 520), rng.randint(190, 680)
        draw.line((x, y, x + rng.randint(10, 60), y + rng.randint(-4, 4)), fill=0, width=3)
    if noise:
        # A second pass through the scanner: a shift and speckle. One pixel here is
        # far more, relative to stroke width, than a real 300 dpi re-scan moves.
        image = image.transform(image.size, Image.AFFINE, (1, 0, noise, 0, 1, noise), fillcolor=255)
        speckle = random.Random(seed + 1000)
        for _ in range(300):
            image.putpixel((speckle.randint(0, 599), speckle.randint(0, 849)), 0)
    image.save(path)
    return str(path)


@pytest.fixture
def month(tmp_path):
    revision = tmp_path / "revision"
    revision.mkdir()
    for n in range(1, 9):
        _sheet(revision / f"01-09-2026_p{n}.jpg", seed=n)
    return str(revision)


def test_a_rescan_of_the_same_sheets_is_recognised(month, tmp_path):
    rescans = [_sheet(tmp_path / f"r{n}.jpg", seed=n, noise=1) for n in (3, 4, 5, 6)]
    matches = already_read(rescans, month)
    assert matches is not None
    assert [os.path.basename(e) for _, e, _ in matches] == [
        f"01-09-2026_p{n}.jpg" for n in (3, 4, 5, 6)]
    assert all(score >= MATCH for *_, score in matches)


def test_new_paper_is_read(month, tmp_path):
    new = [_sheet(tmp_path / f"n{n}.jpg", seed=100 + n) for n in range(4)]
    assert already_read(new, month) is None


def test_one_new_sheet_among_old_ones_means_the_scan_is_read(month, tmp_path):
    """Skipping a new sheet would lose it; reading an old one costs a little."""
    mixed = [_sheet(tmp_path / "a.jpg", seed=1, noise=1), _sheet(tmp_path / "b.jpg", seed=999)]
    assert already_read(mixed, month) is None


def test_two_sheets_cannot_both_claim_the_same_original(month, tmp_path):
    twice = [_sheet(tmp_path / "x.jpg", seed=2, noise=1), _sheet(tmp_path / "y.jpg", seed=2, noise=1)]
    matches = already_read(twice, month)
    assert matches is None or len({e for _, e, _ in matches}) == 2


def test_an_empty_month_matches_nothing(tmp_path):
    empty = tmp_path / "vacio"
    empty.mkdir()
    assert already_read([_sheet(tmp_path / "s.jpg", seed=1)], str(empty)) is None


def test_different_sheets_score_well_below_the_bar(tmp_path):
    a = signature(_sheet(tmp_path / "a.jpg", seed=1))
    b = signature(_sheet(tmp_path / "b.jpg", seed=2))
    assert similarity(a, b) < MATCH


class TestTheProcessorSetsItAside:
    def test_no_reading_is_paid_for_and_the_file_is_kept(self, app, tmp_path, monkeypatch):
        from entry_store import EntryStore
        from processed_ledger import ProcessedLedger
        from spend_guard import SpendGuard

        revision = os.path.join(app.incoming, "2026", "SEPTIEMBRE", ".revision")
        os.makedirs(revision, exist_ok=True)
        for n in range(1, 5):
            _sheet(os.path.join(revision, f"15-09-2026_p{n}.jpg"), seed=n)
        rescans = [_sheet(tmp_path / f"r{n}.jpg", seed=n, noise=1) for n in range(1, 5)]
        monkeypatch.setattr(app, "page_images", lambda path, workdir: rescans)

        def must_not_read(*a, **k):
            raise AssertionError("a re-scan must not be read")
        monkeypatch.setattr(app, "read_page_with_consensus", must_not_read)
        scan = os.path.join(app.incoming, "2026", "SEPTIEMBRE", "SKM_R.pdf")
        with open(scan, "wb") as handle_:
            handle_.write(b"rescan")
        ledger = ProcessedLedger(str(tmp_path / "p.sqlite3"))
        with EntryStore(str(tmp_path / "e.sqlite3")) as store:
            outcome = app.process_scan(scan, ledger, SpendGuard(str(tmp_path / "s.sqlite3"), 5, 1.1),
                                       store)
        assert outcome == "duplicate-paper"
        kept = os.path.join(app.incoming, "2026", "SEPTIEMBRE", ".duplicados", "SKM_R.pdf")
        assert os.path.isfile(kept) and not os.path.exists(scan)
        assert ledger.already_processed(kept)

    def test_the_duplicates_folder_is_never_scanned(self):
        from month_folders import is_in_archive
        assert is_in_archive("incoming/2026/SEPTIEMBRE/duplicados/SKM_R.pdf", "incoming")


def test_signatures_of_saved_sheets_are_cached_and_pruned(month, tmp_path):
    import same_paper
    same_paper._CACHE.clear()
    already_read([_sheet(tmp_path / "n.jpg", seed=500)], month)
    assert len(same_paper._CACHE) == 8
    other = tmp_path / "otro"
    other.mkdir()
    _sheet(other / "02-10-2026_p1.jpg", seed=1)
    already_read([_sheet(tmp_path / "m.jpg", seed=501)], str(other))
    assert [os.path.basename(k[0]) for k in same_paper._CACHE] == ["02-10-2026_p1.jpg"]
