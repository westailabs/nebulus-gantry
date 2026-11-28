"""CPA demo mode, issue 3.3: rehearsal matchers and run logic, without Nebulus or an LLM."""
import importlib.util
import json
import sys
import urllib.error
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("cpa_demo_rehearse", REPO / "scripts" / "cpa_demo_rehearse.py")
rh = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("cpa_demo_rehearse", rh)
_spec.loader.exec_module(rh)

CARDS = rh.load_cards()
EXPECTED = rh.load_expected()
CORPUS = rh.corpus_files()
SAMPLE_TEXT = {f.name: f.read_text() for f in (REPO / "scripts" / "fixtures" / "cpa_demo_samples").glob("SAMPLE_*.txt")}


# ── fixture integrity ───────────────────────────────────────────────────────


def test_every_card_has_expected_facts_and_nothing_extra():
    assert {c["id"] for c in CARDS} == set(EXPECTED["cards"])
    assert len(CARDS) == 4


def test_card_list_has_no_engagement_letter_or_tax_law_research_prompt():
    for c in CARDS:
        text = f"{c['label']} {c['prompt']}".lower()
        assert "engagement letter" not in text
        assert "tax law" not in text and "tax-law" not in text and "research" not in text


def test_load_cards_rejects_an_engagement_letter_card(tmp_path):
    bad = tmp_path / "cards.json"
    bad.write_text(json.dumps({"cards": [{"id": "x", "label": "Draft an engagement letter", "prompt": "Draft it"}]}))
    with pytest.raises(ValueError):
        rh.load_cards(bad)


@pytest.mark.parametrize("card_id", sorted(EXPECTED["cards"]))
def test_every_expected_fact_and_source_is_in_the_synthetic_corpus(card_id):
    exp = EXPECTED["cards"][card_id]
    for src in exp["sources"]:
        assert src in CORPUS
    corpus_text = " ".join(SAMPLE_TEXT[s] for s in exp["sources"])
    for alts in exp["facts"]:
        assert not rh.missing_facts(corpus_text, [alts]), f"{alts[0]!r} not in {exp['sources']}"


def test_the_ui_and_the_rehearsal_read_the_same_card_file():
    ui_cards = json.loads((REPO / "frontend" / "src" / "demo" / "cpaStarterCards.json").read_text())["cards"]
    assert [c["prompt"] for c in ui_cards] == [c["prompt"] for c in CARDS]


# ── matchers ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize("answer,ok", [
    ("The total proposed amount due is $765, and the response is due by 2026-10-02.", True),
    ("They owe **$765.00**; respond by October 2, 2026 [1].", True),
    ("They owe $765; respond by Oct 2, 2026.", True),
    ("They owe $7,650; respond by 2026-10-02.", False),
    ("They owe $765.", False),
])
def test_fact_matching_cp2000(answer, ok):
    assert (rh.missing_facts(answer, EXPECTED["cards"]["irs-notice"]["facts"]) == []) is ok


def test_fact_matching_ignores_case_and_whitespace():
    facts = [["Sample Catering Co"], ["$4,100", "4,100"]]
    assert rh.missing_facts("SAMPLE\u00a0catering co. paid 4,100.", facts) == []
    assert rh.missing_facts("Sample Catering Co. paid $14,100.", facts) == [["$4,100", "4,100"]]


def test_citation_rules():
    exp = ["SAMPLE_whitfield_irs_cp2000_2024.txt"]
    good = [{"filename": "SAMPLE_whitfield_irs_cp2000_2024.txt", "chunk_index": 0}]
    assert rh.citation_problems(good, CORPUS, exp) == []
    assert rh.citation_problems([], CORPUS, exp) == ["no citations"]
    wrong = [{"filename": "SAMPLE_okafor_2025_form1040_summary.txt", "chunk_index": 0}]
    assert rh.citation_problems(wrong, CORPUS, exp) == [f"no citation from {exp}"]
    outside = good + [{"filename": "client_real_return.pdf", "chunk_index": 2}]
    assert "outside the SAMPLE corpus" in rh.citation_problems(outside, CORPUS, exp)[0]


def test_audit_rules():
    row = {"action": "chat.query", "detail": {"correlation_id": "abc", "message_id": 5}}
    assert rh.audit_problems(row, "abc", 5) == []
    assert rh.audit_problems(None, "abc", 5) == ["no chat.query audit row found"]
    assert rh.audit_problems({**row, "action": "auth.login"}, "abc", 5)
    assert rh.audit_problems(row, "zzz", 5) == ["audit row correlation_id does not match the answer"]


def test_evaluate_card_pass_and_refusal():
    card = next(c for c in CARDS if c["id"] == "irs-notice")
    result = {
        "answer": "The CP2000 proposes $765 in total; the response is due 2026-10-02 [1].",
        "sources": [{"filename": "SAMPLE_whitfield_irs_cp2000_2024.txt", "chunk_index": 0}],
        "meta": {"correlation_id": "c1"}, "message_id": 9,
        "audit": {"action": "chat.query", "detail": {"correlation_id": "c1", "message_id": 9}},
    }
    assert rh.evaluate_card(card, EXPECTED["cards"]["irs-notice"], result, CORPUS) == []
    refused = {**result, "meta": {"refused": True, "correlation_id": "c1"}}
    assert "answer was a no-source refusal" in rh.evaluate_card(card, EXPECTED["cards"]["irs-notice"], refused, CORPUS)


# ── run(): dry run makes no calls; live run gates the exit code ────────────


def _args(tmp_path, *, apply=False, url="http://127.0.0.1:9000", yes=False):
    pw = tmp_path / "pw"
    pw.write_text("not-a-real-password-xyz\n")
    return SimpleNamespace(url=url, email="sarah.chen@gantry-demo.example.com", password_file=pw,
                           log=tmp_path / "rehearse.log", apply=apply, yes=yes, keep_threads=False)


def test_dry_run_makes_no_api_or_llm_calls_and_logs_the_plan(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("dry run must not touch the network")

    monkeypatch.setattr("urllib.request.urlopen", boom)
    monkeypatch.setattr("urllib.request.OpenerDirector.open", boom)
    assert rh.run(_args(tmp_path), api_factory=boom) == 0
    log = (tmp_path / "rehearse.log").read_text()
    assert "DRY-RUN" in log and "no API or LLM calls made" in log
    for c in CARDS:
        assert c["id"] in log


def test_live_refuses_non_loopback_without_yes(tmp_path):
    def boom(*a, **k):
        raise AssertionError("must refuse before connecting")

    assert rh.run(_args(tmp_path, apply=True, url="http://10.1.2.3:9000"), api_factory=boom) == 2


GOOD_ANSWERS = {
    "missing-documents": ("Whitfield, Okafor and Vega have open requests [1].", "SAMPLE_document_requests_2026-11.txt"),
    "irs-notice": ("It proposes $765 in total, due 2026-10-02 [1].", "SAMPLE_whitfield_irs_cp2000_2024.txt"),
    "client-1099s": ("Sample Catering Co. $4,100; Example Card Payments Co. $38,640 [1].", "SAMPLE_whitfield_2025_1099_summary.txt"),
    "yoy-return-changes": ("AGI rose from $79,630 to $89,214 [1].", "SAMPLE_whitfield_2025_form1040_summary.txt"),
}


class FakeApi:
    def __init__(self, answers, audit=True, me_role="user"):
        self.answers, self.audit, self.me_role = answers, audit, me_role
        self.calls, self.deleted, self._conv, self._last = [], [], 0, {}

    def login(self, email, password_file):
        return {"email": email, "role": self.me_role}

    def chat(self, conv_id, prompt):
        card = next(c for c in CARDS if c["prompt"] == prompt)
        text, src = self.answers[card["id"]]
        self._last[conv_id] = conv_id * 10
        return text, [{"filename": src, "chunk_index": 0, "similarity": 0.5}], {"correlation_id": f"cid{conv_id}"}, 1.2

    def req(self, method, path, body=None):
        self.calls.append((method, path))
        if path == "/api/documents/collections":
            return [{"id": 3, "name": "SAMPLE Clients (synthetic)"}]
        if method == "POST" and path == "/api/chat/conversations":
            self._conv += 1
            return {"id": self._conv}
        if method == "PATCH":
            return {}
        if method == "GET" and path.startswith("/api/chat/conversations/"):
            cid = int(path.rsplit("/", 1)[1])
            return {"messages": [{"role": "user", "id": cid * 10 - 1}, {"role": "assistant", "id": cid * 10}]}
        if path.startswith("/api/chat/messages/"):
            mid = int(path.split("/")[4])
            if not self.audit:
                raise urllib.error.HTTPError(path, 404, "nf", {}, None)
            return {"id": mid, "action": "chat.query", "detail": {"correlation_id": f"cid{mid // 10}", "message_id": mid}}
        if method == "DELETE":
            self.deleted.append(path)
            return {}
        raise AssertionError(path)


def test_live_all_cards_pass_and_threads_are_cleaned_up(tmp_path):
    api = FakeApi(GOOD_ANSWERS)
    assert rh.run(_args(tmp_path, apply=True), api_factory=lambda url: api) == 0
    assert len(api.deleted) == 4
    log = (tmp_path / "rehearse.log").read_text()
    assert log.count(" PASS ") == 4 and "4/4 cards passed" in log
    assert "not-a-real-password-xyz" not in log


def test_live_fails_when_a_fact_is_missing(tmp_path):
    answers = {**GOOD_ANSWERS, "irs-notice": ("It proposes $765 [1].", "SAMPLE_whitfield_irs_cp2000_2024.txt")}
    assert rh.run(_args(tmp_path, apply=True), api_factory=lambda url: FakeApi(answers)) == 1
    assert "missing expected fact '2026-10-02'" in (tmp_path / "rehearse.log").read_text()


def test_live_fails_when_the_citation_is_wrong(tmp_path):
    answers = {**GOOD_ANSWERS, "client-1099s": (GOOD_ANSWERS["client-1099s"][0], "SAMPLE_okafor_2025_form1040_summary.txt")}
    assert rh.run(_args(tmp_path, apply=True), api_factory=lambda url: FakeApi(answers)) == 1


def test_live_fails_without_an_audit_row(tmp_path):
    assert rh.run(_args(tmp_path, apply=True), api_factory=lambda url: FakeApi(GOOD_ANSWERS, audit=False)) == 1
    assert "no chat.query audit row found" in (tmp_path / "rehearse.log").read_text()


def test_live_non_loopback_needs_yes_and_https(tmp_path):
    def boom(*a, **k):
        raise AssertionError("must refuse before connecting")

    assert rh.run(_args(tmp_path, apply=True, url="http://10.1.2.3:9000", yes=True), api_factory=boom) == 2
    assert "must use https" in (tmp_path / "rehearse.log").read_text()
    assert rh.target_refusal("https://demo.example.org", True) is None


def test_live_requires_url_and_password_file(tmp_path):
    def boom(*a, **k):
        raise AssertionError("must refuse before connecting")

    args = _args(tmp_path, apply=True)
    args.url = ""
    assert rh.run(args, api_factory=boom) == 2
    args = _args(tmp_path, apply=True)
    args.password_file = None
    assert rh.run(args, api_factory=boom) == 2
