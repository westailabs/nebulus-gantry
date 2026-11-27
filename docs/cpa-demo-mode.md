# CPA demo mode

One runtime switch turns a normal Gantry instance into the CPA demo profile. It is a
profile, not a fork: the same code and build serve both, and the flag only changes what
the UI shows.

## Switches

| Variable | Default | Effect |
|---|---|---|
| `GANTRY_DEMO_MODE` | off | `true`, `1` or `yes` (any case) turns on the CPA demo profile. Anything else, or unset, leaves Gantry unchanged. |
| `GANTRY_DEMO_FIRM_NAME` | empty | Fictional firm name for the demo welcome screen and header. Empty shows no firm name. Never use a real firm or client. |

Both are read from the backend's environment at startup and served, read-only and without
authentication, by `GET /api/config`:

```json
{"demo_mode": true, "demo_firm_name": "Sample & Co. CPAs"}
```

The frontend fetches this on load, so an instance can switch profiles with an env change
and a backend restart, without rebuilding the frontend. If the fetch fails the UI stays in
the normal (non-demo) profile.

## What the flag changes

With the flag off, every item below stays exactly as it is in normal Gantry.

- **Dev chrome (non-admins only).** No Situation Map toggle or panel (so no Halt All or
  Daily Budget), no model picker (messages go out with no model override, so the
  instance's configured model is used), no Orchestrator tab, and `/orchestrator` redirects
  home. Admins keep all of it for setup.
- **Starter cards.** Four questions over Client Files replace the four code cards. The copy
  lives in `frontend/src/data/cpaStarterCards.json`, which the rehearsal script reads too.
- **Client Files.** The Knowledge Vault pane is labeled "Client Files" and starts open.
- **Audit link.** Each assistant answer has a "View audit entry" link that opens its
  `chat.query` row (your own answers only). See `docs/audit-log-and-citations.md`.
