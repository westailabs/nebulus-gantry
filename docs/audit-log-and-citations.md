# Audit log and structured citations

Merged to develop in #4 (d827ab4); pre-demo hardening in #5.

## Audit log
- Table `audit_events` (created automatically). `user_id` is not a foreign key, so rows outlive user deletion.
  Timestamps are UTC and the API returns them with a `+00:00` offset.
- Recorded actions: `auth.login`, `auth.login_failed`, `auth.logout`, `auth.password_change`,
  `user.create`, `user.update` (`role_before`, `role_after`, `password_changed`; never the password),
  `user.delete`, `persona.create` / `persona.update` / `persona.delete` (system and user personas;
  `detail.changed` lists the fields sent in the request), `conversation.scope_change` (the new
  scope as a validated `[{type, id}]` list; malformed scopes are rejected with 422 before any change),
  `chat.dispatch` (the `/api/chat/dispatch` path, with outcome in `finally`), `document.upload`, `document.upload_failed`, `document.delete`,
  `document.view_source`, `chat.query`, `conversation.export` (json/pdf/excel/report),
  `conversation.bulk_export`, `audit.export` (`rows`, `total`, `truncated`).
- `chat.query` is written in a `finally` block, so every request gets a row. `detail.outcome` is one of
  `completed`, `no_match` (refused, no source), `retrieval_error` (document search failed),
  `llm_error` / `empty_answer` (with `error_type`), `client_aborted` (disconnect or cancel), or `error`.
  Each row also carries retrieved doc ids, model, latency, a `correlation_id` (also returned in the
  stream's `done` metadata) and the stored assistant `message_id`.
  A retrieval error always refuses, even with `GANTRY_REFUSE_WITHOUT_SOURCES=false`. A disconnect
  during a refusal is recorded as `client_aborted`.
  Citations are not attached to failed answers, and long-term memory is updated only for `completed`.
- CSV export neutralises spreadsheet formulas: cells starting with `= + - @ TAB CR` get a leading `'`.
- Audit write failures never break a request. A failed write is rolled back and retried once (so a
  session left failed by earlier work doesn't lose the row). A write that still fails is logged at
  ERROR with a traceback and counted in-process. `GET /api/admin/audit` returns the count as
  `audit_write_failures`. The count is per worker process and resets on restart.

### Query text and privacy: what the flag does and does not cover
- `GANTRY_AUDIT_STORE_QUERY_TEXT=true` stores query text **in the audit table only**. The default
  stores only the query length. When stored, SSN, EIN and email patterns are redacted
  (`GANTRY_AUDIT_REDACT`, default `true`).
- The flag does **not** control chat history. Conversations are saved in `messages` as before (that is
  the product's chat history), and if long-term memory is configured, completed turns are embedded
  there as well. A deployment that must not keep client text has to run without LTM and apply a
  conversation retention policy. Both are outside this branch.

### Per-answer audit link (CPA demo mode)

With `GANTRY_DEMO_MODE` on, every saved assistant answer shows a "View audit entry" link. It
calls `GET /api/chat/messages/{message_id}/audit`, which returns the `chat.query` row whose
`detail.message_id` matches, but only if the caller wrote that row for a conversation they
own. Admins get no wider view through this route; the full list and CSV stay under
`/api/admin/audit`. The response leaves out `ip_address` and keeps only the non-sensitive
`detail` keys (outcome, refused, scoped, model, correlation_id, message_id, timing). The
route returns 404 when demo mode is off. Audit rows already keep `message_id` in their JSON
`detail` (no column, no migration), so the link keys on it. Refusals now record their
`message_id` too, and the refusal `done` event carries `correlation_id` like a normal answer.
Refusal rows written before that have no `message_id`; for those the link falls back to
`GET /api/chat/conversations/{id}/audit`, the caller's own `chat.query` rows for that one
thread (404 for threads they don't own, demo mode only, no `ip_address`), and the viewer
says it is showing the thread's entries.

## Citations
- When a conversation has a document scope, the scope goes into the vector query itself as a Chroma
  `where` clause (collection ids OR document ids), so out-of-scope chunks can't crowd out in-scope ones.
- Hits below `GANTRY_MIN_SOURCE_SIMILARITY` or without a document id are dropped. Not set at all:
  the floor is off. Explicit `0`: off, on purpose. Set but blank, or not a number (`0,42`, `abc`,
  `nan`): the floor falls back to the recommended `0.42` (an invalid value also logs a WARNING),
  so a typo can't silently turn the floor off. If nothing is left, the question is refused.
  A bounded lexical (BM25-style) boost may be added to the dense similarity before the floor is
  applied, so an exact-term near-miss such as "What was the Whitfield AGI?" (dense 0.3986) can
  clear a 0.42 floor. The floor value itself is not changed. The boost is at most
  `GANTRY_KEYWORD_BOOST_MAX` (default `0.05`, capped at `0.10`), only applies when the dense
  score is within `GANTRY_KEYWORD_BOOST_WINDOW` (default `0.06`) of the floor, and only when
  weighted query-term coverage in the chunk (or filename) is at least
  `GANTRY_KEYWORD_BOOST_MIN_SCORE` (default `0.5`). Set `GANTRY_KEYWORD_BOOST=off` to disable.
  The public `/api/documents/search` path is unboosted, so `calibrate` still measures raw
  dense similarity.
  The value is clamped to [0, 1]. **Recommended for the CPA demo: `0.42`**, which is committed in `.env.example` and is the
  `docker-compose.yml` default. Under compose a blank value also gets 0.42, so only an explicit `0`
  turns the floor off (the app itself now treats a blank value the same way). The demo instance (not started by compose) must set
  `GANTRY_MIN_SOURCE_SIMILARITY=0.42` in its own env.
- Pre-demo check: run `scripts/cpa_demo_smoke.py feature` against the demo instance and expect
  `off-topic in scope ... refused=True`. `calibrate` reads raw similarities from
  `POST /api/documents/search`, which applies no floor, so it still works while the floor is on. Calibrated on 2026-11-22 against the
  SAMPLE corpus with Chroma's default embedding: on-topic top hits were 0.458–0.548, and generic
  off-topic questions were 0.334–0.412. A same-domain question about an absent client
  ("Acme Corp payroll tax", 0.456) still passes the floor, and the model has to say the documents
  don't cover it. Recalibrate whenever the corpus or the embedding model changes
  (`scripts/cpa_demo_smoke.py calibrate`). The top chunks are numbered and placed in the system prompt, and the
  model is told to cite them as `[n]`.
- The backend streams `event: sources` (`n, document_id, filename, chunk_index, similarity, snippet`)
  before the answer, includes `sources` in the `done` metadata, and saves them on the assistant message (`messages.sources`).
- UI: source chips under the answer, and inline `[n]` markers that open the cited chunk
  (`GET /api/documents/{id}/chunks/{i}`, which is audited as `document.view_source`).
- No source retrieved means a refusal without calling the LLM (`GANTRY_REFUSE_WITHOUT_SOURCES`, default `true`).
  If the vector store is down, the user gets a separate "document search unavailable" message,
  which is audited as `retrieval_error` and not as a refusal.

### Run this before every demo

Run `python scripts/cpa_demo_rehearse.py --apply` against the demo instance, logged in as
the walkthrough user (`GANTRY_SMOKE_EMAIL`, `GANTRY_SMOKE_PASSWORD_FILE`), before every
demo. It asks every CPA starter card (the same `frontend/src/demo/cpaStarterCards.json` the
UI shows) against the `SAMPLE Clients (synthetic)` collection. A card fails unless its answer
holds the expected facts from `scripts/fixtures/cpa_rehearsal_expected.json`, at least one
citation comes from the expected `SAMPLE_*` file, and the turn has a `chat.query` audit row
that the per-answer link can open. The script exits non-zero if any card fails, so don't
demo until it passes. Without `--apply` it only writes the plan to its log and makes no API
or LLM calls. Rehearsal threads are deleted afterwards unless you pass `--keep-threads`.

## Reasoning models
- `reasoning_content` deltas are ignored. Inline `<think>`, `<thinking>` and `<reasoning>` blocks
  (any case) are stripped even when split across chunks.
- A lone closing tag (from templates that prefill `<think>`) means the text before it was reasoning.
  The server then sends `event: replace` with the cleaned answer, and the UI swaps the bubble text.
  The cleaned text is what gets stored.
- Templates that prefill `<think>`: set `GANTRY_REASONING_PREFILLED=true`. Output is then held
  until the first closing tag, so reasoning never reaches the client. If no closing tag arrives,
  the held text is released at the end, unless the model hit its token limit
  (`finish_reason=length`). In that case the held text is cut-off reasoning, so it's dropped and the
  empty-answer notice is shown. The demo model (nemotron-bolt via llama-server) puts
  reasoning in `reasoning_content` and no tags in content (checked with `scripts/cpa_demo_smoke.py probe`),
  so the demo leaves this off. A cleaned answer that is blank becomes the empty-answer notice.
- An answer that comes back empty gets an explicit retry message instead of a blank bubble.
  Raw LLM exception text is not sent to the client.
- `NEBULUS_LLM_MAX_TOKENS` optionally caps the completion length. The stream read timeout is 180 s.

## Known limits / deferred (Plumb review on PR #4)
- Audit rows share the request's DB session and are written in a separate commit, not in the same
  transaction as the action. A dedicated audit session/outbox is deferred.
- The table is append-only at the application layer only. It is not tamper-evident (no hash chain
  or WORM storage). There is no retention policy, and unauthenticated failed logins
  (`auth.login_failed` rows) aren't rate-limited.
- Literal `<think>` / `</think>` text in a real answer is over-stripped (N4). This is acceptable for
  the demo.
- `client_ip` uses the socket peer address. `X-Forwarded-For` behind a trusted proxy is not handled yet.
