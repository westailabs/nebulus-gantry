# Audit log and structured citations

Added on `feat/audit-log-citations` (not yet merged).

## Audit log
- Table `audit_events` (created automatically). `user_id` is not a foreign key, so rows outlive user deletion.
- Recorded actions: `auth.login`, `auth.login_failed`, `auth.logout`, `document.upload`,
  `document.upload_failed`, `document.delete`, `document.view_source`, `chat.query`
  (retrieved doc ids, model, latency, `refused`), `conversation.export` (json/pdf/excel/report),
  `conversation.bulk_export`, `audit.export`.
- Query text is stored only when `GANTRY_AUDIT_STORE_QUERY_TEXT=true`. The default stores only the query length.
- Admin API: `GET /api/admin/audit?action=&user_id=&limit=&offset=` and `GET /api/admin/audit/export.csv`.
- UI: Admin → Audit.
- Limits: entries are append-only at the application layer. The table is not tamper-evident (no hash chain or WORM storage), and there is no retention policy yet.

## Citations
- When a conversation has a document scope, the top chunks are numbered and placed in the
  system prompt, and the model is told to cite them as `[n]`.
- The backend streams `event: sources` (`n, document_id, filename, chunk_index, similarity, snippet`)
  before the answer, includes `sources` in the `done` metadata, and saves them on the assistant message (`messages.sources`).
- UI: source chips under the answer, and inline `[n]` markers that open the cited chunk
  (`GET /api/documents/{id}/chunks/{i}`, which is audited as `document.view_source`).
- No source retrieved means a refusal without calling the LLM (`GANTRY_REFUSE_WITHOUT_SOURCES`, default `true`).

## Reasoning models
- `reasoning_content` deltas are ignored, and inline `<think>…</think>` blocks are stripped even when split across chunks.
- An answer that comes back empty gets an explicit retry message instead of a blank bubble.
- `NEBULUS_LLM_MAX_TOKENS` optionally caps the completion length. The stream read timeout is 180 s.
