# Audit log and structured citations

Added on `feat/audit-log-citations` (not yet merged).

## Audit log
- Table `audit_events` (created automatically). `user_id` is not a foreign key, so rows outlive user deletion.
  Timestamps are UTC and the API returns them with a `+00:00` offset.
- Recorded actions: `auth.login`, `auth.login_failed`, `auth.logout`, `auth.password_change`,
  `user.create`, `user.update` (`role_before`, `role_after`, `password_changed`; never the password),
  `user.delete`, `document.upload`, `document.upload_failed`, `document.delete`,
  `document.view_source`, `chat.query`, `conversation.export` (json/pdf/excel/report),
  `conversation.bulk_export`, `audit.export` (`rows`, `total`, `truncated`).
- `chat.query` is written in a `finally` block, so every request gets a row. `detail.outcome` is one of
  `completed`, `no_match` (refused, no source), `retrieval_error` (document search failed),
  `llm_error` / `empty_answer` (with `error_type`), `client_aborted` (disconnect or cancel), or `error`.
  Each row also carries retrieved doc ids, model, latency and a `correlation_id`.
  Citations are not attached to failed answers, and long-term memory is updated only for `completed`.
- CSV export neutralises spreadsheet formulas: cells starting with `= + - @ TAB CR` get a leading `'`.
- Audit write failures never break a request. They are logged at ERROR and counted in-process.

### Query text and privacy: what the flag does and does not cover
- `GANTRY_AUDIT_STORE_QUERY_TEXT=true` stores query text **in the audit table only**. The default
  stores only the query length. When stored, SSN, EIN and email patterns are redacted
  (`GANTRY_AUDIT_REDACT`, default `true`).
- The flag does **not** control chat history. Conversations are saved in `messages` as before (that is
  the product's chat history), and if long-term memory is configured, completed turns are embedded
  there as well. A deployment that must not keep client text has to run without LTM and apply a
  conversation retention policy. Both are outside this branch.

## Citations
- When a conversation has a document scope, the scope goes into the vector query itself as a Chroma
  `where` clause (collection ids OR document ids), so out-of-scope chunks can't crowd out in-scope ones.
- Hits below `GANTRY_MIN_SOURCE_SIMILARITY` (default `0`, which turns the floor off) or without a
  document id are dropped. The top chunks are numbered and placed in the system prompt, and the
  model is told to cite them as `[n]`.
- The backend streams `event: sources` (`n, document_id, filename, chunk_index, similarity, snippet`)
  before the answer, includes `sources` in the `done` metadata, and saves them on the assistant message (`messages.sources`).
- UI: source chips under the answer, and inline `[n]` markers that open the cited chunk
  (`GET /api/documents/{id}/chunks/{i}`, which is audited as `document.view_source`).
- No source retrieved means a refusal without calling the LLM (`GANTRY_REFUSE_WITHOUT_SOURCES`, default `true`).
  If the vector store is down, the user gets a separate "document search unavailable" message,
  which is audited as `retrieval_error` and not as a refusal.

## Reasoning models
- `reasoning_content` deltas are ignored. Inline `<think>`, `<thinking>` and `<reasoning>` blocks
  (any case) are stripped even when split across chunks.
- A lone closing tag (from templates that prefill `<think>`) means the text before it was reasoning.
  The server then sends `event: replace` with the cleaned answer, and the UI swaps the bubble text.
  The cleaned text is what gets stored.
- An answer that comes back empty gets an explicit retry message instead of a blank bubble.
  Raw LLM exception text is not sent to the client.
- `NEBULUS_LLM_MAX_TOKENS` optionally caps the completion length. The stream read timeout is 180 s.

## Known limits / deferred (Plumb review on PR #4)
- Audit rows share the request's DB session and are written in a separate commit, not in the same
  transaction as the action. A dedicated audit session/outbox is deferred.
- The table is append-only at the application layer only. It is not tamper-evident (no hash chain
  or WORM storage). There is no retention policy and no rate limit on the audit endpoints.
- `client_ip` uses the socket peer address. `X-Forwarded-For` behind a trusted proxy is not handled yet.
