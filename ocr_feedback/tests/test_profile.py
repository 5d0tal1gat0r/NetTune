import pathlib

import pytest

from ocr_feedback.profile import ProfileError, load_profile, parse_profile

REPO = pathlib.Path(__file__).resolve().parents[2]


def _data(**over):
    data = {"system": "toy", "stages": [{"name": "ocr", "kind": "reads"}]}
    data.update(over)
    return data


def test_minimal_profile_gets_defaults():
    p = parse_profile(_data())
    assert p.system == "toy"
    assert [s.name for s in p.stages] == ["ocr"]
    assert p.same_line == 0.72 and p.fold_accents and p.strip_punctuation
    assert p.section_field == "section" and p.tag_name == "tag"


@pytest.mark.parametrize("bad", [
    {"stages": []},
    {"stages": [{"name": "x", "kind": "guess"}]},
    {"stages": [{"name": "x", "kind": "reads"}, {"name": "x", "kind": "select"}]},
    {"stages": [{"kind": "reads"}]},
    {"system": ""},
])
def test_invalid_profiles_are_refused(bad):
    with pytest.raises(ProfileError):
        parse_profile(_data(**bad))


def test_threshold_must_be_a_ratio():
    with pytest.raises(ProfileError):
        parse_profile(_data(align={"same_line": 1.5}))


def test_nettune_profile_loads():
    p = load_profile(REPO / "feedback" / "nettune.toml")
    assert p.system == "nettune"
    assert [(s.name, s.kind) for s in p.stages] == [
        ("passes", "reads"), ("consensus", "select"),
        ("filtered", "select"), ("omitted", "drop")]
    assert [s.name for s in p.capture_stages()] == ["passes", "consensus", "filtered"]
    assert [s.name for s in p.drop_stages()] == ["omitted"]
    assert p.tag_name == "block"
    assert len(p.source_hash) == 64
