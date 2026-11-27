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
- **Model override (always on, not tied to the flag).** The API ignores the `model` field
  of a chat message from a non-admin, in demo mode and in normal Gantry alike, so only an
  admin can trigger a server-side model switch. With the flag off a non-admin still sees
  the model picker, but the instance's configured model answers.
- **Starter cards.** Four questions over Client Files replace the four code cards. The copy
  lives in `frontend/src/demo/cpaStarterCards.json`, which the rehearsal script reads too.
- **Client Files.** The Knowledge Vault pane is labeled "Client Files" and starts open.
- **Persona prompt.** The chat system prompt says "Client Files" instead of "Knowledge Vault"
  to match the pane. The stored persona and the flag-off prompt are unchanged.
- **Audit link.** Each saved assistant answer has a "View audit entry" link that opens its
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
`GET /api/config` reports `demo_mode: true`, and refuses a non-loopback target unless
`--yes` is given and the URL is https.

```bash
# placeholders: use your instance's backend URL and your own password files
export GANTRY_SMOKE_URL=http://127.0.0.1:<backend-port>
export GANTRY_SMOKE_PASSWORD_FILE=<file holding the admin password>
export GANTRY_DEMO_USER_PASSWORD_FILE=<file holding the walkthrough user's password>
# plan only (reads, no writes)
python scripts/cpa_demo_seed.py --log <path>/cpa_demo_seed.log
# then make the changes
python scripts/cpa_demo_seed.py --apply --log <path>/cpa_demo_seed.log
```

The admin and the walkthrough user must be different accounts: if `--user-email` is the admin's
own address the script refuses (dry run and `--apply`) rather than demote the admin, and it never
changes the last remaining admin to a user.

It makes sure that:

1. The walkthrough user is a non-admin, `sarah.chen@gantry-demo.example.com`, shown as
   "Sarah Chen, CPA". The account is created if missing, and its name and role are fixed if
   they differ.
2. No account is shown as "Demo Admin". The setup admin is renamed "Setup Admin" and stays
   an admin for setup only; don't use it for the walkthrough.
3. Leftover threads owned by the admin or by the walkthrough user are deleted only when the
   title starts with `Moto`, `Smoke` or `Probe`, or is just `test`, `tests`, `testing` or
   `debug` (optionally numbered). A title that merely contains the word ("Safe-harbor test",
   "Attestation prep", "Contest notes") is kept. The dry run lists each thread it
   would delete (owner, id, title) in the log. Other users' threads are never touched.
4. The walkthrough user has a `SAMPLE Clients (synthetic)` collection with every
   `scripts/fixtures/cpa_demo_samples/SAMPLE_*.txt` file. Missing files are uploaded. A
   same-named document whose content differs from the repo file is replaced (deleted, then
   re-uploaded; the plan shows `replace_sample`). Content is compared by the server's hash
   when the API reports one, otherwise by byte size (`file_size`), which is what
   `GET /api/documents` returns today.
5. Any collection whose name doesn't read as synthetic is reported, never deleted.

Passwords come only from files and are never printed. The script never opens the Gantry
database or `.env` files. Set `GANTRY_SEED_FORBIDDEN_ROOTS` (an `os.pathsep`-separated list of
directories) to make it refuse to read from, say, another checkout on the same host.

### Live redeploy: remove the old CP2000 copy before reseeding

An instance seeded before the payer rename still holds the old
`SAMPLE_whitfield_irs_cp2000_2024.txt` (its Reason line names a real-sounding catering
company instead of "Sample Catering Co. (fictional)"). The seed replaces a stale copy only in
the walkthrough user's `SAMPLE Clients (synthetic)` collection, so on a live redeploy remove
every old copy by hand first. Written down for the operator; nothing runs it automatically.

1. Take the usual pre-redeploy database backup (the redeploy runbook does this).
2. For each account that owns a SAMPLE collection (the walkthrough user, and the setup admin
   if earlier smoke runs uploaded samples there), list its documents with
   `GET /api/documents?collection_id=<id>` while signed in as that account, and note the
   `id` and `file_size` of `SAMPLE_whitfield_irs_cp2000_2024.txt`.
3. Compare with `wc -c < scripts/fixtures/cpa_demo_samples/SAMPLE_whitfield_irs_cp2000_2024.txt`
   from the commit being deployed. A copy whose size differs is the old one. (If you open it
   in Client Files to check the payer, that view is recorded in the audit log.)
4. Delete each old copy in Client Files, or with `DELETE /api/documents/<id>` as its owner.
   Do the same for any other sample whose size differs (the 2025 Form 1040 summary and the
   engagement letter also changed).
5. Run the seed dry run. It should plan `upload_sample` (not `replace_sample`) for the CP2000
   and the other removed files, and nothing for the unchanged ones. Then run `--apply`, and
   re-run `scripts/cpa_demo_smoke.py calibrate` because the corpus changed.

## Rehearsal

Run `scripts/cpa_demo_rehearse.py --apply` before every demo. See "Run this before every
demo" in `docs/audit-log-and-citations.md`.
