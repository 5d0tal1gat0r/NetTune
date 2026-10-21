import json
import os
import sys
import textwrap

from ocr_feedback.cli import main


def test_export_with_a_toy_adapter(tmp_path, monkeypatch, capsys):
    (tmp_path / "toy_adapter.py").write_text(textwrap.dedent("""
        from ocr_feedback.model import FinalLine, Page

        class T:
            def __init__(self, word):
                self.word = word
            def pages(self):
                return [Page("p1")]
            def final_lines(self, page_id):
                return [FinalLine("1", self.word, None, "confirmed", source_text=self.word)]

        def make(word):
            return T(word)
    """))
    (tmp_path / "toy.toml").write_text(
        'system = "toy"\n[[stages]]\nname = "ocr"\nkind = "reads"\n')
    monkeypatch.syspath_prepend(str(tmp_path))
    code = main(["export", "--profile", str(tmp_path / "toy.toml"),
                 "--adapter", "toy_adapter:make", "--adapter-arg", "word=hola",
                 "--out", str(tmp_path / "ds"), "--label", "t"])
    assert code == 0
    folder = capsys.readouterr().out.strip().splitlines()[-1]
    assert folder.endswith("toy-t")
    with open(os.path.join(folder, "lines.jsonl"), encoding="utf-8") as handle:
        assert json.loads(handle.readline())["final"] == "hola"
    sys.modules.pop("toy_adapter", None)


def test_adapter_is_closed_when_the_feedback_db_is_unusable(tmp_path, monkeypatch):
    import pytest

    (tmp_path / "toy_adapter2.py").write_text(textwrap.dedent("""
        CLOSED = []

        class T:
            def pages(self):
                return []
            def final_lines(self, page_id):
                return []
            def close(self):
                CLOSED.append(True)

        def make():
            return T()
    """))
    (tmp_path / "toy.toml").write_text(
        'system = "toy"\n[[stages]]\nname = "ocr"\nkind = "reads"\n')
    (tmp_path / "bad.sqlite3").write_text("not a database")
    monkeypatch.syspath_prepend(str(tmp_path))
    try:
        with pytest.raises(Exception):
            main(["export", "--profile", str(tmp_path / "toy.toml"),
                  "--feedback-db", str(tmp_path / "bad.sqlite3"),
                  "--adapter", "toy_adapter2:make", "--out", str(tmp_path / "ds")])
        assert sys.modules["toy_adapter2"].CLOSED == [True]
    finally:
        sys.modules.pop("toy_adapter2", None)
