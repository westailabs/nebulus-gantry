#!/usr/bin/env python3
"""Pre-demo rehearsal: run every CPA starter card and check facts, citations and the audit row.

Run this before every demo (CPA demo mode, issue 3.3). The cards come from
frontend/src/demo/cpaStarterCards.json, the same file the UI renders, and the expected
facts from scripts/fixtures/cpa_rehearsal_expected.json. Synthetic SAMPLE documents only.

  python scripts/cpa_demo_rehearse.py            # dry run: writes the plan to the log,
                                                 # makes no API and no LLM calls
  python scripts/cpa_demo_rehearse.py --apply    # live: ask every card, exit 1 if any fails

A live card passes only if (1) the answer contains every expected fact, (2) at least one
citation comes from an expected SAMPLE_* file of the corpus, and (3) a chat.query audit
row exists for the turn: through the per-answer deep-link (demo mode), else, for an admin
login, through the admin audit list by correlation id. Latency is logged, never gated.

Config (env, same convention as cpa_demo_smoke.py): GANTRY_SMOKE_URL (default
http://127.0.0.1:8013), GANTRY_SMOKE_EMAIL, GANTRY_SMOKE_PASSWORD_FILE (password is read
from this file only and never printed), GANTRY_REHEARSE_LOG (default cpa_demo_rehearse.log).
Use the walkthrough user's login to rehearse exactly what the buyer will see.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CARDS_FILE = REPO_ROOT / "frontend" / "src" / "demo" / "cpaStarterCards.json"
EXPECTED_FILE = REPO_ROOT / "scripts" / "fixtures" / "cpa_rehearsal_expected.json"
CORPUS_DIR = REPO_ROOT / "scripts" / "fixtures" / "cpa_demo_samples"
FORBIDDEN_CARD_TEXT = re.compile(r"engagement letter|tax[- ]law|internal revenue code|\bresearch\b", re.IGNORECASE)


# ── Pure helpers (unit-tested in backend/tests/test_cpa_demo_rehearse.py) ──


def load_cards(path: Path = CARDS_FILE) -> list[dict]:
    cards = json.loads(path.read_text())["cards"]
    for c in cards:
        if FORBIDDEN_CARD_TEXT.search(f"{c['label']} {c['prompt']}"):
            raise ValueError(f"card {c['id']!r} is an engagement-letter or tax-law research prompt")
    return cards


def load_expected(path: Path = EXPECTED_FILE) -> dict:
    return json.loads(path.read_text())


def corpus_files(corpus_dir: Path = CORPUS_DIR) -> set[str]:
    return {f.name for f in corpus_dir.glob("SAMPLE_*.txt")}


def normalize(text: str) -> str:
    text = (text or "").replace("\u2011", "-").replace("\u2013", "-").replace("\u2014", "-")
    text = text.replace("\u00a0", " ").replace("**", "")
    return re.sub(r"\s+", " ", text).strip().lower()


def _fact_pattern(spelling: str) -> re.Pattern:
    s = normalize(spelling)
    pat = re.escape(s)
    if s[:1].isdigit() or s[:1] == "$":
        pat = r"(?<![\d,])" + pat
    if s[-1:].isdigit():
        pat = pat + r"(?![\d,]\d|\d)"
    return re.compile(pat)


def missing_facts(answer: str, facts: list[list[str]]) -> list[list[str]]:
    """Facts (each a list of acceptable spellings) with no spelling in the answer."""
    text = normalize(answer)
    return [alts for alts in facts if not any(_fact_pattern(a).search(text) for a in alts)]


def citation_problems(sources: list[dict] | None, corpus: set[str], expected_sources: list[str]) -> list[str]:
    sources = sources or []
    if not sources:
        return ["no citations"]
    problems = []
    outside = [s.get("filename") for s in sources if s.get("filename") not in corpus]
    if outside:
        problems.append(f"citations outside the SAMPLE corpus: {outside}")
    if not any(s.get("filename") in expected_sources for s in sources):
        problems.append(f"no citation from {expected_sources}")
    return problems


def audit_problems(entry: dict | None, correlation_id: str | None, message_id: int | None) -> list[str]:
    if not entry:
        return ["no chat.query audit row found"]
    problems = []
    if entry.get("action") != "chat.query":
        problems.append(f"audit row action is {entry.get('action')!r}")
    detail = entry.get("detail") or {}
    if correlation_id and detail.get("correlation_id") != correlation_id:
        problems.append("audit row correlation_id does not match the answer")
    if message_id is not None and detail.get("message_id") not in (None, message_id):
        problems.append("audit row message_id does not match the answer")
    return problems


def evaluate_card(card: dict, expected: dict, result: dict, corpus: set[str]) -> list[str]:
    """All reasons the card failed; empty means pass."""
    problems = []
    if result.get("error"):
        return [f"request failed: {result['error']}"]
    if not (result.get("answer") or "").strip():
        problems.append("empty answer")
    if (result.get("meta") or {}).get("refused"):
        problems.append("answer was a no-source refusal")
    for alts in missing_facts(result.get("answer", ""), expected["facts"]):
        problems.append(f"missing expected fact {alts[0]!r}")
    problems += citation_problems(result.get("sources"), corpus, expected["sources"])
    problems += audit_problems(result.get("audit"), (result.get("meta") or {}).get("correlation_id"),
                               result.get("message_id"))
    return problems


def is_loopback(url: str) -> bool:
    return (urllib.parse.urlparse(url).hostname or "") in ("localhost", "127.0.0.1", "::1")


# ── Live API access (reuses cpa_demo_smoke's helpers) ───────────────────────


class Api:
    """Thin wrapper over scripts/cpa_demo_smoke.py's req/chat, pointed at ``url``."""

    def __init__(self, url: str):
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import cpa_demo_smoke as smoke  # noqa: E402 -- reuse its cookie-jar client

        smoke.BASE = url.rstrip("/")
        self.smoke = smoke

    def req(self, method, path, body=None):
        return self.smoke.req(method, path, body)

    def chat(self, conv_id, prompt):
        return self.smoke.chat(conv_id, prompt)

    def login(self, email: str, password_file: Path) -> dict:
        self.req("POST", "/api/auth/login", {"email": email, "password": password_file.read_text().strip()})
        return self.req("GET", "/api/auth/me")


def _find_collection(api, name: str) -> dict | None:
    cols = api.req("GET", "/api/documents/collections")
    cols = cols.get("collections", cols) if isinstance(cols, dict) else cols
    matches = [c for c in cols if c["name"] == name] or [c for c in cols if c["name"].startswith("SAMPLE Clients")]
    return matches[-1] if matches else None


def _audit_entry(api, me: dict, message_id: int | None, correlation_id: str | None) -> dict | None:
    if message_id is not None:
        try:
            return api.req("GET", f"/api/chat/messages/{message_id}/audit")
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise
    if me.get("role") == "admin" and correlation_id:
        events = api.req("GET", "/api/admin/audit?action=chat.query&limit=200")["events"]
        return next((e for e in events if (e.get("detail") or {}).get("correlation_id") == correlation_id), None)
    return None


def ask_card(api, me: dict, collection_id: int, card: dict) -> dict:
    conv = api.req("POST", "/api/chat/conversations", {})
    result: dict = {"conversation_id": conv["id"]}
    try:
        api.req("PATCH", f"/api/chat/conversations/{conv['id']}/document-scope",
                {"document_scope": [{"type": "collection", "id": collection_id}]})
        answer, sources, meta, latency = api.chat(conv["id"], card["prompt"])
        result.update(answer=answer, sources=sources or (meta or {}).get("sources"), meta=meta or {},
                      latency_s=latency)
        detail = api.req("GET", f"/api/chat/conversations/{conv['id']}")
        assistants = [m for m in detail["messages"] if m["role"] == "assistant"]
        result["message_id"] = assistants[-1]["id"] if assistants else None
        result["audit"] = _audit_entry(api, me, result["message_id"], result["meta"].get("correlation_id"))
    except urllib.error.HTTPError as e:
        result["error"] = f"HTTP {e.code} on {urllib.parse.urlparse(e.url).path}"
    return result


# ── Main ────────────────────────────────────────────────────────────────────


class Log:
    def __init__(self, path: Path):
        self.path = path.expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def __call__(self, msg: str) -> None:
        line = f"{datetime.now(timezone.utc).isoformat(timespec='seconds')} {msg}"
        print(line)
        with self.path.open("a") as fh:
            fh.write(line + "\n")


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Rehearse every CPA demo starter card.")
    p.add_argument("--url", default=os.getenv("GANTRY_SMOKE_URL", "http://127.0.0.1:8013"))
    p.add_argument("--email", default=os.getenv("GANTRY_SMOKE_EMAIL", "sarah.chen@gantry-demo.example.com"))
    p.add_argument("--password-file", type=Path, default=Path(os.getenv(
        "GANTRY_SMOKE_PASSWORD_FILE", str(Path.home() / "demo/gantry-cpa/.secrets/demo_user_password"))))
    p.add_argument("--log", type=Path, default=Path(os.getenv("GANTRY_REHEARSE_LOG", "cpa_demo_rehearse.log")))
    p.add_argument("--apply", action="store_true", help="live run against the instance (default: dry run)")
    p.add_argument("--yes", action="store_true", help="allow a non-loopback target")
    p.add_argument("--keep-threads", action="store_true", help="keep the rehearsal threads (default: delete)")
    return p.parse_args(argv)


def run(args, api_factory=Api) -> int:  # noqa: C901 -- linear script flow
    log = Log(args.log)
    cards = load_cards()
    expected = load_expected()
    corpus = corpus_files()
    missing = [c["id"] for c in cards if c["id"] not in expected["cards"]]
    if missing:
        log(f"fixture has no expected facts for card(s) {missing}")
        return 2
    log(f"cpa_demo_rehearse {'LIVE' if args.apply else 'DRY-RUN'} target={args.url} user={args.email} "
        f"collection={expected['collection']!r} cards={len(cards)}")
    for c in cards:
        exp = expected["cards"][c["id"]]
        log(f"card {c['id']}: {c['label']!r} prompt={c['prompt']!r} "
            f"facts={[alts[0] for alts in exp['facts']]} sources={exp['sources']}")
    if not args.apply:
        log("dry run: no API or LLM calls made. Re-run with --apply for the live rehearsal.")
        return 0
    if not is_loopback(args.url) and not args.yes:
        log("refused: target is not loopback; re-run with --yes if that is intended")
        return 2

    api = api_factory(args.url)
    me = api.login(args.email, args.password_file)
    col = _find_collection(api, expected["collection"])
    if col is None:
        log(f"FAIL: {args.email} has no {expected['collection']!r} collection; run scripts/cpa_demo_seed.py")
        return 1
    failures = 0
    for card in cards:
        t0 = time.monotonic()
        result = ask_card(api, me, col["id"], card)
        problems = evaluate_card(card, expected["cards"][card["id"]], result, corpus)
        cites = [f"{s.get('filename')}#{s.get('chunk_index')}@{s.get('similarity')}" for s in result.get("sources") or []]
        audit = result.get("audit") or {}
        log(f"{'PASS' if not problems else 'FAIL'} {card['id']} latency={result.get('latency_s')}s "
            f"wall={round(time.monotonic() - t0, 1)}s sources={cites} audit_id={audit.get('id')} "
            f"correlation={(result.get('meta') or {}).get('correlation_id')}")
        log(f"  answer: {(result.get('answer') or '')[:600]!r}")
        for p in problems:
            log(f"  problem: {p}")
        failures += bool(problems)
        if not args.keep_threads and result.get("conversation_id"):
            try:
                api.req("DELETE", f"/api/chat/conversations/{result['conversation_id']}")
            except urllib.error.HTTPError:
                log(f"  note: could not delete rehearsal thread {result['conversation_id']}")
    log(f"rehearsal {'PASSED' if not failures else 'FAILED'}: {len(cards) - failures}/{len(cards)} cards passed")
    return 1 if failures else 0


def main(argv=None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
