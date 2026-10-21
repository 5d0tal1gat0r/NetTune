from ocr_feedback.align import best_match, normalize, ratio
from ocr_feedback.model import Line
from ocr_feedback.profile import parse_profile

P = parse_profile({"system": "t", "stages": [{"name": "o", "kind": "reads"}]})


def test_normalize_folds_and_strips():
    assert normalize("  • Revisión, CUADRO!  ") == "revision cuadro"
    assert normalize("Revisión", fold_accents=False) == "revisión"


def test_ratio_ignores_case_and_accents():
    assert ratio("REVISIÓN cuadro", "revision cuadro", P) == 1.0


def test_best_match_threshold():
    lines = [Line("Se abre Z6"), Line("Conectando mq de aire")]
    hit, score = best_match("Se abre 26", lines, P)
    assert hit.text == "Se abre Z6" and score >= P.same_line
    miss, score = best_match("Algo completamente distinto", lines, P)
    assert miss is None and score < P.same_line
