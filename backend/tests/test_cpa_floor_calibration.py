"""Pins both sides of the CPA demo similarity floor (0.42) on recorded scores.

Dense scores come from scripts/fixtures/cpa_floor_calibration.json (recorded on a live
throwaway instance); the keyword boost runs for real on the real SAMPLE texts. So a change to
the floor, the boost settings or the sample files that would refuse a starter card, or let a
generic off-topic question through, fails here.
"""
import json
from pathlib import Path

import pytest

from backend.services.keyword_boost import apply_boost, fold_plural, lexical_score, tokenize

REPO = Path(__file__).resolve().parents[2]
FIXTURE = json.loads((REPO / "scripts" / "fixtures" / "cpa_floor_calibration.json").read_text())
SAMPLES = REPO / "scripts" / "fixtures" / "cpa_demo_samples"
FLOOR = 0.42  # the committed recommendation (.env.example, compose default, launcher)


def _final(query: str, filename: str, dense: float) -> tuple[float, float]:
    return apply_boost(query, (SAMPLES / filename).read_text(), dense, FLOOR, filename=filename,
                       max_boost=0.05, window=0.06, min_score=0.5)


def test_fixture_cards_match_the_starter_cards_and_expected_sources():
    cards = json.loads((REPO / "frontend/src/demo/cpaStarterCards.json").read_text())["cards"]
    expected = json.loads((REPO / "scripts/fixtures/cpa_rehearsal_expected.json").read_text())["cards"]
    assert [c["id"] for c in FIXTURE["cards"]] == [c["id"] for c in cards]
    for rec, card in zip(FIXTURE["cards"], cards):
        assert rec["prompt"] == card["prompt"]
        assert rec["file"] in expected[card["id"]]["sources"]


@pytest.mark.parametrize("rec", FIXTURE["cards"], ids=lambda r: r["id"])
def test_every_starter_card_clears_the_floor(rec):
    final, _ = _final(rec["prompt"], rec["file"], rec["dense"])
    assert final >= FLOOR, f"{rec['id']} would be refused: {final:.4f} < {FLOOR}"


def test_missing_documents_card_needs_the_boost_and_gets_it():
    # PR #11's case: dense 0.417 is just under 0.42; 'documents' vs 'document' (plural folding)
    # lifts lexical coverage over the 0.5 minimum so the boost fires.
    rec = next(r for r in FIXTURE["cards"] if r["id"] == "missing-documents")
    assert rec["dense"] < FLOOR
    final, boost = _final(rec["prompt"], rec["file"], rec["dense"])
    assert boost > 0 and final >= FLOOR + 0.02


GENERIC = [r for r in FIXTURE["off_topic"] if r["kind"] == "generic"]


def test_the_off_topic_list_is_committed_and_has_the_near_miss():
    assert len(GENERIC) >= 4
    assert max(r["dense"] for r in GENERIC) >= 0.38  # sourdough bread, the closest generic miss


@pytest.mark.parametrize("rec", GENERIC, ids=lambda r: r["query"][:30])
def test_generic_off_topic_questions_stay_below_the_floor(rec):
    final, _ = _final(rec["query"], rec["file"], rec["dense"])
    assert final < FLOOR, f"{rec['query']!r} would no longer be refused: {final:.4f}"


def test_margin_on_both_sides_is_at_least_two_hundredths():
    low = min(_final(r["prompt"], r["file"], r["dense"])[0] for r in FIXTURE["cards"])
    high = max(_final(r["query"], r["file"], r["dense"])[0] for r in GENERIC)
    assert low - FLOOR >= 0.02 and FLOOR - high >= 0.02


class TestPluralFolding:
    @pytest.mark.parametrize("raw,folded", [
        ("documents", "document"), ("requests", "request"), ("clients", "client"),
        ("entries", "entry"), ("class", "class"), ("status", "status"), ("analysis", "analysis"),
        ("tax", "tax"), ("is", "is"), ("was", "was"), ("agi", "agi"), ("1099s", "1099"),
    ])
    def test_fold_plural(self, raw, folded):
        assert fold_plural(raw) == folded

    def test_tokenize_folds_so_plural_query_meets_singular_text(self):
        assert tokenize("Missing DOCUMENTS") == ["missing", "document"]
        assert lexical_score("documents", "one document") == 1.0

    def test_unrelated_text_still_scores_zero(self):
        assert lexical_score("documents missing", "the weather is nice") == 0.0
