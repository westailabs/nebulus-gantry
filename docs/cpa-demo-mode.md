# CPA demo mode

One runtime switch turns a normal Gantry instance into the CPA demo profile. It is a
profile, not a fork: the same code and build serve both, and the flag only changes what
the UI shows.

## Switches

| Variable | Default | Effect |
|---|---|---|
| `GANTRY_DEMO_MODE` | off | `true`, `1` or `yes` (any case) turns on the CPA demo profile. Anything else, or unset, leaves Gantry unchanged. |
| `GANTRY_DEMO_FIRM_NAME` | empty | Fictional firm name for the demo welcome screen and header. Empty shows no firm name. Never use a real firm or client. The demo uses `Sample & Co. CPAs` (quote it in an env file). |

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
  lives in `frontend/src/demo/cpaStarterCards.json`, which the rehearsal script reads too.
- **Client Files.** The Knowledge Vault pane is labeled "Client Files" and starts open.
- **Audit link.** Each assistant answer has a "View audit entry" link that opens its
  `chat.query` row (your own answers only). See `docs/audit-log-and-citations.md`.
- **White-label.** The welcome screen shows `GANTRY_DEMO_FIRM_NAME` (if set) above the
  greeting and a small "Powered by West AI Labs" line; the header shows the firm name next
  to the product mark. No logos, and no IRS, SOC 2, Safeguards or HIPAA claims anywhere in
  the demo UI.
- **Welcome copy.** The subtitle is "Your data stays on your own hardware" and the
  motorcycle emoji becomes the Gantry mark. There is deliberately no offline or "network
  not required" badge until a pulled-network rehearsal passes.

## Seeding the demo instance

`scripts/cpa_demo_seed.py` resets an instance for the walkthrough. It is re-runnable, a dry
run by default, and logs every step (default `cpa_demo_seed.log`, or `--log`). It talks only
to the instance API, so its changes are audited. It refuses to write unless
`GET /api/config` reports `demo_mode: true`, and refuses non-loopback targets without
`--yes`.

```bash
# plan only (reads, no writes)
GANTRY_SMOKE_PASSWORD_FILE=~/demo/gantry-cpa/.secrets/admin_password \
GANTRY_DEMO_USER_PASSWORD_FILE=~/demo/gantry-cpa/.secrets/demo_user_password \
  python scripts/cpa_demo_seed.py --log ~/.nebulus/logs/gantry-cpa-seed.log
# then make the changes
python scripts/cpa_demo_seed.py --apply --log ~/.nebulus/logs/gantry-cpa-seed.log
```

It makes sure that:

1. The walkthrough user is a non-admin, `sarah.chen@gantry-demo.example.com`, shown as
   "Sarah Chen, CPA". The account is created if missing, and its name and role are fixed if
   they differ.
2. No account is shown as "Demo Admin". The setup admin is renamed "Setup Admin" and stays
   an admin for setup only; don't use it for the walkthrough.
3. Leftover threads ("Moto test", "smoke", "probe", "test", "debug") owned by the admin or
   by the walkthrough user are deleted. Other users' threads are left alone.
4. The walkthrough user has a `SAMPLE Clients (synthetic)` collection with every
   `scripts/fixtures/cpa_demo_samples/SAMPLE_*.txt` file. Only missing files are uploaded.
5. Any collection whose name doesn't read as synthetic is reported, never deleted.

Passwords come only from files and are never printed. The script never opens the Gantry
database, `.env` files, or anything under `~/projects/nebulus-gantry`.

## Rehearsal

Run `scripts/cpa_demo_rehearse.py --apply` before every demo. See "Run this before every
demo" in `docs/audit-log-and-citations.md`.
