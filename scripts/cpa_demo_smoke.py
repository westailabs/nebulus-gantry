#!/usr/bin/env python3
"""Smoke test / similarity calibration for a Gantry demo instance. Never prints secrets.

Config (env): GANTRY_SMOKE_URL (default http://127.0.0.1:8013), GANTRY_SMOKE_EMAIL,
GANTRY_SMOKE_PASSWORD_FILE (a file holding the password; never pass it on the command line),
GANTRY_SMOKE_SAMPLES (dir of SAMPLE_*.txt synthetic docs), GANTRY_SMOKE_LLM_URL and
GANTRY_SMOKE_LLM_MODEL (for probe). Use synthetic documents only.

  basic   : login + one chat
  feature : + upload synthetic docs, scoped chat, sources, chunk viewer, audit log, refusal
  calibrate: top-source similarity for on-topic vs off-topic questions (latest SAMPLE collection)
  probe   : does llama-server put reasoning in content (<think> tags) or reasoning_content?
"""
import http.cookiejar
import json
import os
import sys
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

BASE = os.getenv("GANTRY_SMOKE_URL", "http://127.0.0.1:8013")
EMAIL = os.getenv("GANTRY_SMOKE_EMAIL", "admin@gantry-demo.example.com")
PW_FILE = Path(os.getenv("GANTRY_SMOKE_PASSWORD_FILE",
                         str(Path.home() / "demo/gantry-cpa/.secrets/admin_password")))
SAMPLES = Path(os.getenv("GANTRY_SMOKE_SAMPLES", str(Path.home() / "demo/gantry-cpa-samples")))
LLM_URL = os.getenv("GANTRY_SMOKE_LLM_URL", "http://127.0.0.1:8090")
LLM_MODEL = os.getenv("GANTRY_SMOKE_LLM_MODEL", "nemotron-bolt")
jar = http.cookiejar.CookieJar()
op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def req(method, path, body=None, raw=False, headers=None, timeout=180):
    h = {"Content-Type": "application/json"} if body is not None and not isinstance(body, bytes) else {}
    h.update(headers or {})
    data = json.dumps(body).encode() if body is not None and not isinstance(body, bytes) else body
    r = op.open(urllib.request.Request(BASE + path, data=data, method=method, headers=h), timeout=timeout)
    out = r.read().decode(errors="replace")
    return out if raw else (json.loads(out) if out else None)


def upload(name, text, collection_id):
    b = uuid.uuid4().hex
    parts = (f"--{b}\r\nContent-Disposition: form-data; name=\"collection_id\"\r\n\r\n{collection_id}\r\n"
             f"--{b}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{name}\"\r\n"
             f"Content-Type: text/plain\r\n\r\n{text}\r\n--{b}--\r\n").encode()
    return req("POST", "/api/documents/upload", parts, headers={"Content-Type": f"multipart/form-data; boundary={b}"})


def chat(conv_id, q):
    t = time.monotonic()
    raw = req("POST", f"/api/chat/conversations/{conv_id}/messages", {"content": q}, raw=True, timeout=300)
    content, sources, meta, ev = "", None, None, None
    for line in raw.splitlines():
        if line.startswith("event: "):
            ev = line[7:].strip()
        elif line.startswith("data: "):
            d = json.loads(line[6:])
            if ev == "sources":
                sources = d
            elif ev == "done":
                meta = d
            else:
                content += d.get("content", "")
            ev = None
    return content, sources, meta, round(time.monotonic() - t, 2)


ON_TOPIC = [
    "What adjusted gross income did we file for Dana Whitfield for tax year 2025?",
    "What amount did the IRS CP2000 notice propose for Whitfield?",
    "What does the engagement letter say about fees?",
    "What was Okafor's filing status?",
    "When was the Whitfield 2025 return filed?",
    "Summarize Okafor's 2025 Form 1040.",
]
OFF_TOPIC = [
    "What did we file for a client named Zed Quinn?",
    "What is the capital of France?",
    "Write a haiku about the ocean.",
    "What was Acme Corp's Q3 payroll tax deposit?",
    "Who won the 1998 World Cup?",
    "What is the recipe for sourdough bread?",
]


def _sample_collection():
    cols = req("GET", "/api/documents/collections")
    cols = cols.get("collections", cols) if isinstance(cols, dict) else cols
    matches = [c for c in cols if c["name"].startswith("SAMPLE Clients")]
    if not matches:
        sys.exit("No 'SAMPLE Clients' collection on this instance. Run 'feature' once first "
                 "to upload the synthetic SAMPLE_* documents.")
    return matches[-1]


def calibrate():
    """Raw similarities via POST /api/documents/search, which applies no floor, so the
    margin is measurable even while GANTRY_MIN_SOURCE_SIMILARITY is active. Read-only;
    makes no LLM calls."""
    col = _sample_collection()
    for label, qs in (("ON ", ON_TOPIC), ("OFF", OFF_TOPIC)):
        for q in qs:
            res = req("POST", "/api/documents/search",
                      {"query": q, "collection_ids": [col["id"]], "top_k": 3})["results"]
            sims = [round(x["similarity"], 4) for x in res]
            print(f"{label} top={max(sims) if sims else None} sims={sims} q={q[:50]!r}")
    print("Pick a floor between the lowest ON top and the highest OFF top; set it as "
          "GANTRY_MIN_SOURCE_SIMILARITY in the instance env.")


def probe():
    body = {"model": LLM_MODEL, "stream": True, "max_tokens": 200,
            "messages": [{"role": "user", "content": "What is 17*3? Answer briefly."}]}
    r = urllib.request.urlopen(urllib.request.Request(
        f"{LLM_URL}/v1/chat/completions", data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"}), timeout=120)
    content, reasoning = "", ""
    for line in r.read().decode().splitlines():
        if line.startswith("data: ") and line[6:].strip() != "[DONE]":
            d = (json.loads(line[6:]).get("choices") or [{}])[0].get("delta", {})
            content += d.get("content") or ""
            reasoning += d.get("reasoning_content") or ""
    low = content.lower()
    print(f"probe: reasoning_content chars={len(reasoning)} content chars={len(content)} "
          f"content_has_open={'<think>' in low} content_has_close={'</think>' in low} content={content[:80]!r}")


def _is_loopback(url: str) -> bool:
    host = urllib.parse.urlparse(url).hostname or ""
    return host in ("localhost", "127.0.0.1", "::1")


def main():
    args = [a for a in sys.argv[1:] if a != "--yes"]
    mode = args[0] if args else "basic"
    if mode not in ("basic", "feature", "calibrate", "probe"):
        sys.exit(f"unknown mode {mode!r}; use basic | feature | calibrate | probe [--yes]")
    if mode == "probe":
        return probe()
    print(f"target: {BASE} mode: {mode}")
    if mode == "feature" and not _is_loopback(BASE) and "--yes" not in sys.argv:
        sys.exit("feature mode creates collections, uploads, conversations and exports on the "
                 "target. It isn't loopback; re-run with --yes if that's intended.")
    req("POST", "/api/auth/login", {"email": EMAIL, "password": PW_FILE.read_text().strip()})
    print("login ok; me:", req("GET", "/api/auth/me").get("email"))
    if mode == "calibrate":
        return calibrate()
    conv = req("POST", "/api/chat/conversations", {})
    c, _, m, dt = chat(conv["id"], "In one sentence, what does a CPA firm do?")
    print(f"basic chat {dt}s tokens/s={m and m.get('tokens_per_second')} answer={c[:300]!r}")
    if mode != "feature":
        return
    col = req("POST", "/api/documents/collections", {"name": "SAMPLE Clients (synthetic)"})
    docs_dir = SAMPLES
    ids = []
    for f in sorted(docs_dir.glob("SAMPLE_*.txt")):
        d = upload(f.name, f.read_text(), col["id"])
        ids.append(d["id"])
        print("uploaded", f.name, d.get("status"), "chunks", d.get("chunk_count"))
    conv2 = req("POST", "/api/chat/conversations", {})
    req("PATCH", f"/api/chat/conversations/{conv2['id']}/document-scope",
        {"document_scope": [{"type": "collection", "id": col["id"]}]})
    q = "What adjusted gross income did we file for Harbor Lane Bakery LLC owner Dana Whitfield for tax year 2025?"
    c, s, m, dt = chat(conv2["id"], q)
    print(f"scoped chat {dt}s answer={c[:400]!r}")
    print("sources:", json.dumps(s)[:600])
    if s:
        first = s[0]
        ch = req("GET", f"/api/documents/{first['document_id']}/chunks/{first['chunk_index']}")
        print("chunk viewer:", ch["filename"], "chunk", ch["chunk_index"], "text starts:", ch["text"][:80].replace("\n", " "))
    # refusal: empty collection
    col2 = req("POST", "/api/documents/collections", {"name": "Empty (synthetic)"})
    conv3 = req("POST", "/api/chat/conversations", {})
    req("PATCH", f"/api/chat/conversations/{conv3['id']}/document-scope",
        {"document_scope": [{"type": "collection", "id": col2["id"]}]})
    c, s, m, dt = chat(conv3["id"], "What did we file for a client named Zed Quinn?")
    print(f"refusal check {dt}s sources={s} answer={c[:200]!r}")
    # off-topic in a populated scope: needs GANTRY_MIN_SOURCE_SIMILARITY
    conv4 = req("POST", "/api/chat/conversations", {})
    req("PATCH", f"/api/chat/conversations/{conv4['id']}/document-scope",
        {"document_scope": [{"type": "collection", "id": col["id"]}]})
    c, s, m, dt = chat(conv4["id"], "What is the capital of France?")
    print(f"off-topic in scope {dt}s refused={bool(m and m.get('refused'))} sources={len(s or [])} answer={c[:120]!r}")
    # reload conversation: sources persisted?
    det = req("GET", f"/api/chat/conversations/{conv2['id']}")
    am = [x for x in det["messages"] if x["role"] == "assistant"][-1]
    print("persisted sources on reload:", len(am.get("sources") or []))
    req("GET", f"/api/chat/conversations/{conv2['id']}/export?format=json", raw=True)
    ev = req("GET", "/api/admin/audit?limit=50")
    print("audit total:", ev["total"])
    for e in ev["events"][:12]:
        print("  ", e["timestamp"], e["user_email"], e["action"], "docs=", e.get("doc_ids"), "q=", (e.get("query_text") or "")[:50])
    csv = req("GET", "/api/admin/audit/export.csv", raw=True)
    print("csv header:", csv.splitlines()[0], "rows:", len(csv.splitlines()) - 1)


if __name__ == "__main__":
    main()
