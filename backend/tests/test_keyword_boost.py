"""Bounded lexical boost for RAG retrieval, including the Whitfield AGI near-miss."""

from unittest.mock import MagicMock, patch

from backend.services.document_service import DocumentService
from backend.services.keyword_boost import (
    DEFAULT_MAX_BOOST,
    apply_boost,
    boost_settings,
    lexical_score,
    query_terms,
)

WHITFIELD_QUERY = "What was the Whitfield AGI?"
WHITFIELD_CHUNK = "Dana Whitfield Form 1040 for tax year 2025. Line 11 Adjusted Gross Income (AGI): $84,210."
WHITFIELD_FILENAME = "dana_whitfield_2025_1040.txt"
# Calibrated demo miss: dense similarity 0.3986 vs floor 0.42.
WHITFIELD_DENSE = 0.3986
FLOOR = 0.42


class TestLexicalScore:
    def test_whitfield_query_terms(self):
        assert query_terms(WHITFIELD_QUERY) == ["whitfield", "agi"]

    def test_both_terms_in_chunk_score_one(self):
        assert lexical_score(WHITFIELD_QUERY, WHITFIELD_CHUNK) == 1.0

    def test_filename_can_supply_the_client_name(self):
        # A 1040 body excerpt may say "AGI" without repeating the taxpayer name;
        # the filename still identifies the client.
        body = "Line 11 Adjusted Gross Income (AGI): $84,210."
        assert lexical_score(WHITFIELD_QUERY, body) < 0.5
        assert lexical_score(WHITFIELD_QUERY, f"{WHITFIELD_FILENAME} {body}") == 1.0

    def test_unrelated_chunk_scores_zero(self):
        assert (
            lexical_score(WHITFIELD_QUERY, "Quarterly weather outlook for Dallas.")
            == 0.0
        )

    def test_stopwords_and_short_tokens_ignored(self):
        assert query_terms("What was the q?") == []
        assert lexical_score("What was the q?", "AGI $1") == 0.0


class TestApplyBoost:
    def test_whitfield_near_miss_clears_the_floor(self):
        boosted, boost = apply_boost(
            WHITFIELD_QUERY,
            WHITFIELD_CHUNK,
            WHITFIELD_DENSE,
            FLOOR,
            max_boost=DEFAULT_MAX_BOOST,
            window=0.06,
            min_score=0.5,
        )
        assert boost > 0
        assert boosted >= FLOOR
        # Bounded: cannot jump more than the configured max.
        assert boosted <= WHITFIELD_DENSE + DEFAULT_MAX_BOOST
        assert boosted == WHITFIELD_DENSE + boost

    def test_unrelated_near_miss_is_not_lifted(self):
        boosted, boost = apply_boost(
            WHITFIELD_QUERY,
            "Quarterly weather outlook for Dallas.",
            WHITFIELD_DENSE,
            FLOOR,
            max_boost=DEFAULT_MAX_BOOST,
            window=0.06,
            min_score=0.5,
        )
        assert boost == 0
        assert boosted == WHITFIELD_DENSE
        assert boosted < FLOOR

    def test_matching_chunk_outside_the_window_is_not_lifted(self):
        dense = 0.33  # typical generic off-topic in the CPA calibration
        boosted, boost = apply_boost(
            WHITFIELD_QUERY,
            WHITFIELD_CHUNK,
            dense,
            FLOOR,
            max_boost=DEFAULT_MAX_BOOST,
            window=0.06,
            min_score=0.5,
        )
        assert boost == 0
        assert boosted == dense
        assert dense + DEFAULT_MAX_BOOST < FLOOR  # even a full boost would not reach

    def test_agi_only_does_not_meet_min_score(self):
        # "agi" is shorter than "whitfield", so AGI-only coverage stays below 0.5.
        boosted, boost = apply_boost(
            WHITFIELD_QUERY,
            "Line 11 Adjusted Gross Income (AGI): $84,210.",
            WHITFIELD_DENSE,
            FLOOR,
            filename="other_client_1040.txt",
            max_boost=DEFAULT_MAX_BOOST,
            window=0.06,
            min_score=0.5,
        )
        assert boost == 0
        assert boosted < FLOOR

    def test_disabled_max_boost_is_a_no_op(self):
        boosted, boost = apply_boost(
            WHITFIELD_QUERY,
            WHITFIELD_CHUNK,
            WHITFIELD_DENSE,
            FLOOR,
            max_boost=0.0,
            window=0.06,
            min_score=0.5,
        )
        assert boost == 0
        assert boosted == WHITFIELD_DENSE


class TestBoostSettings:
    def test_defaults(self, monkeypatch):
        monkeypatch.delenv("GANTRY_KEYWORD_BOOST_MAX", raising=False)
        monkeypatch.delenv("GANTRY_KEYWORD_BOOST_WINDOW", raising=False)
        monkeypatch.delenv("GANTRY_KEYWORD_BOOST_MIN_SCORE", raising=False)
        monkeypatch.delenv("GANTRY_KEYWORD_BOOST", raising=False)
        assert boost_settings() == (0.05, 0.06, 0.5)

    def test_flag_disables_boost(self, monkeypatch):
        monkeypatch.setenv("GANTRY_KEYWORD_BOOST", "off")
        assert boost_settings()[0] == 0.0

    def test_max_is_capped(self, monkeypatch):
        monkeypatch.setenv("GANTRY_KEYWORD_BOOST_MAX", "5")
        assert boost_settings()[0] == 0.10

    def test_invalid_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("GANTRY_KEYWORD_BOOST_MAX", "nope")
        monkeypatch.setenv("GANTRY_KEYWORD_BOOST_WINDOW", "nan")
        assert boost_settings()[0] == 0.05
        assert boost_settings()[1] == 0.06


class TestRetrieveSourcesBoost:
    def _svc(self, hits):
        svc = DocumentService(MagicMock())
        return svc, patch.object(svc, "_search", return_value=hits)

    def test_whitfield_fixture_passes_the_unchanged_floor(self, monkeypatch):
        monkeypatch.setenv("GANTRY_MIN_SOURCE_SIMILARITY", "0.42")
        hits = [
            {
                "document_id": 7,
                "filename": WHITFIELD_FILENAME,
                "chunk_text": WHITFIELD_CHUNK,
                "similarity": WHITFIELD_DENSE,
                "chunk_index": 0,
            }
        ]
        svc, p = self._svc(hits)
        with p:
            out = svc.retrieve_sources(
                1, WHITFIELD_QUERY, [{"type": "collection", "id": 1}]
            )
        assert len(out) == 1
        assert out[0]["document_id"] == 7
        assert out[0]["dense_similarity"] == WHITFIELD_DENSE
        assert out[0]["keyword_boost"] > 0
        assert out[0]["similarity"] >= FLOOR
        # The floor setting itself is not changed by the boost path.
        from backend.services.document_service import _min_similarity

        assert _min_similarity() == FLOOR

    def test_unrelated_chunk_at_the_same_dense_score_is_dropped(self, monkeypatch):
        monkeypatch.setenv("GANTRY_MIN_SOURCE_SIMILARITY", "0.42")
        hits = [
            {
                "document_id": 8,
                "filename": "weather.txt",
                "chunk_text": "Quarterly weather outlook for Dallas.",
                "similarity": WHITFIELD_DENSE,
                "chunk_index": 0,
            }
        ]
        svc, p = self._svc(hits)
        with p:
            out = svc.retrieve_sources(
                1, WHITFIELD_QUERY, [{"type": "collection", "id": 1}]
            )
        assert out == []

    def test_boundary_without_keywords_still_inclusive(self, monkeypatch):
        # Same as the PR #5 floor test: query "q" has no boostable terms, so
        # 0.41999 stays under the floor and 0.42 is kept.
        monkeypatch.setenv("GANTRY_MIN_SOURCE_SIMILARITY", "0.42")
        hits = [
            {
                "document_id": 1,
                "filename": "a.txt",
                "chunk_text": "AGI $1",
                "similarity": 0.42,
                "chunk_index": 0,
            },
            {
                "document_id": 2,
                "filename": "a.txt",
                "chunk_text": "AGI $1",
                "similarity": 0.41999,
                "chunk_index": 0,
            },
        ]
        svc, p = self._svc(hits)
        with p:
            out = svc.retrieve_sources(1, "q", [{"type": "collection", "id": 1}])
        assert [h["document_id"] for h in out] == [1]
        assert out[0]["keyword_boost"] == 0
        assert out[0]["dense_similarity"] == 0.42
