#!/usr/bin/env python3
"""Seed / reset a Gantry CPA demo instance for the walkthrough (CPA demo mode, issue 5).

Re-runnable and safe by default: without --apply it only reads and prints the plan.
Every run appends to a log file. Passwords are read from files and never printed or logged.

What it does on a GANTRY_DEMO_MODE=true instance:
  1. Ensures the walkthrough user is a non-admin fictional person, "Sarah Chen, CPA"
     (creates the account if missing; fixes display name / role if not).
  2. Renames any account shown as "Demo Admin" to a plain setup name ("Setup Admin");
     the admin account itself stays for setup.
  3. Deletes leftover test threads owned by the admin and by the walkthrough user whose
     title starts with a known leftover prefix ("Moto ...", "Smoke ...", "Probe ...") or is
     just "test" / "debug" (optionally numbered). Other users' threads are never listed
     or touched, and a title that merely contains "test" ("safe-harbor test") is kept.
  4. Ensures the walkthrough user has a "SAMPLE Clients (synthetic)" collection holding
     every SAMPLE_*.txt synthetic document (uploads only the missing ones).
  5. Logs a warning for any collection (admin's or walkthrough user's) whose name is not
     obviously synthetic. It never deletes collections.

All changes go through the instance's own API, so they are audited like any admin action.
It refuses to write unless GET /api/config reports demo_mode=true on the target, and
refuses non-loopback targets unless --yes is given and the URL is https. It never opens the
Gantry database or .env files; it reads only the sample files and the two password files.

Usage (placeholders; nothing here is host-specific):
  export GANTRY_SMOKE_URL=http://127.0.0.1:<backend-port>
  export GANTRY_SMOKE_PASSWORD_FILE=<file holding the admin password>
  export GANTRY_DEMO_USER_PASSWORD_FILE=<file holding the walkthrough user's password>
  python scripts/cpa_demo_seed.py                 # dry run: plans, logs, changes nothing
  python scripts/cpa_demo_seed.py --apply         # make the changes
Config (flags or env): GANTRY_SMOKE_URL, GANTRY_SMOKE_EMAIL (admin), GANTRY_SMOKE_PASSWORD_FILE
(admin), GANTRY_DEMO_USER_EMAIL, GANTRY_DEMO_USER_PASSWORD_FILE (walkthrough user),
GANTRY_DEMO_SEED_LOG, GANTRY_SEED_FORBIDDEN_ROOTS (os.pathsep-separated directories this script
must never read from, e.g. another checkout).
"""
from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SAMPLES = REPO_ROOT / "scripts" / "fixtures" / "cpa_demo_samples"
DEFAULT_ADMIN_EMAIL = "admin@gantry-demo.example.com"
DEFAULT_USER_EMAIL = "sarah.chen@gantry-demo.example.com"
DEFAULT_USER_DISPLAY = "Sarah Chen, CPA"
DEFAULT_ADMIN_DISPLAY = "Setup Admin"
DEFAULT_FIRM_NAME = "Sample & Co. CPAs"
SAMPLE_COLLECTION = "SAMPLE Clients (synthetic)"
THEATRICAL_ADMIN_NAMES = ("demo admin",)
# Leftover engineering/test threads, anchored to the START of the title: known prefixes
# ("Moto test", "Smoke run", "Probe 2"), or a title that is only test/tests/testing/debug
# with an optional number. A bare word elsewhere never matches, so "safe-harbor test",
# "Attestation prep" and "Contest notes" are kept.
DEFAULT_LEFTOVER_PATTERNS = (
    r"^\s*(moto|smoke|probe)\b",
    r"^\s*(tests?|testing|debug)(\s+\d+)?\s*$",
)
SYNTHETIC_NAME = re.compile(r"\b(sample|synthetic)\b", re.IGNORECASE)
# Directories this script must never read from (e.g. another checkout on the same host).
# Set GANTRY_SEED_FORBIDDEN_ROOTS to an os.pathsep-separated list; empty by default.
FORBIDDEN_ROOTS = tuple(Path(p) for p in os.getenv("GANTRY_SEED_FORBIDDEN_ROOTS", "").split(os.pathsep) if p)


# ── Pure planning helpers (unit-tested without a server) ───────────────────


@dataclass
class Plan:
    actions: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add(self, kind: str, **info) -> None:
        self.actions.append({"action": kind, **info})


def is_leftover_title(title: str, patterns=DEFAULT_LEFTOVER_PATTERNS) -> bool:
    return any(re.search(p, title or "", re.IGNORECASE) for p in patterns)


def is_synthetic_name(name: str) -> bool:
    return bool(SYNTHETIC_NAME.search(name or ""))


def plan_users(users: list[dict], user_email: str, user_display: str, admin_email: str,
               admin_display: str) -> Plan:
    plan = Plan()
    by_email = {u["email"].lower(): u for u in users}
    walk = by_email.get(user_email.lower())
    if walk is None:
        plan.add("create_user", email=user_email, display_name=user_display, role="user")
    else:
        changes = {}
        if walk.get("display_name") != user_display:
            changes["display_name"] = user_display
        if walk.get("role") != "user":
            changes["role"] = "user"
        if changes:
            plan.add("update_user", id=walk["id"], email=walk["email"], **changes)
    for u in users:
        if u["email"].lower() == user_email.lower():
            continue
        if (u.get("display_name") or "").strip().lower() in THEATRICAL_ADMIN_NAMES:
            plan.add("update_user", id=u["id"], email=u["email"], display_name=admin_display)
    if admin_email.lower() == user_email.lower():
        plan.warnings.append("admin and walkthrough user are the same account; use a separate admin")
    return plan


def plan_threads(conversations: list[dict], owner: str, patterns=DEFAULT_LEFTOVER_PATTERNS) -> Plan:
    plan = Plan()
    for c in conversations:
        if is_leftover_title(c.get("title", ""), patterns):
            plan.add("delete_thread", owner=owner, id=c["id"], title=c.get("title"))
    return plan


def plan_samples(existing_filenames: list[str], sample_files: list[Path]) -> Plan:
    plan = Plan()
    have = set(existing_filenames)
    for f in sample_files:
        if f.name not in have:
            plan.add("upload_sample", filename=f.name)
    return plan


def plan_collections(collections: list[dict], owner: str) -> Plan:
    plan = Plan()
    for c in collections:
        if not is_synthetic_name(c.get("name", "")):
            plan.warnings.append(f"{owner}: collection {c.get('name')!r} (id {c.get('id')}) is not "
                                 "obviously synthetic; review it before the demo (not deleted)")
    return plan


def sample_files(samples_dir: Path) -> list[Path]:
    files = sorted(samples_dir.glob("SAMPLE_*.txt"))
    for f in files:
        if not f.name.startswith("SAMPLE_"):
            raise ValueError(f"refusing non-SAMPLE file {f}")
    return files


def is_loopback(url: str) -> bool:
    return (urllib.parse.urlparse(url).hostname or "") in ("localhost", "127.0.0.1", "::1")


def target_refusal(url: str, yes: bool) -> str | None:
    """Why this target must be refused, or None. Non-loopback needs --yes and https."""
    if is_loopback(url):
        return None
    if not yes:
        return "target is not loopback; re-run with --yes if that is intended"
    if urllib.parse.urlparse(url).scheme != "https":
        return "a non-loopback target must use https; refusing to send passwords over plain http"
    return None


def check_path_allowed(path: Path) -> None:
    resolved = path.expanduser().resolve()
    for root in FORBIDDEN_ROOTS:
        try:
            resolved.relative_to(root.resolve())
        except ValueError:
            continue
        raise SystemExit(f"refusing to read {path}: it is inside the forbidden root {root}")


def read_secret(path: Path, what: str) -> str:
    check_path_allowed(path)
    try:
        value = path.expanduser().read_text().strip()
    except OSError as e:
        raise SystemExit(f"cannot read the {what} password file ({e.strerror})") from None
    if not value:
        raise SystemExit(f"the {what} password file is empty")
    return value


# ── HTTP client (one cookie jar per signed-in user) ─────────────────────────


class Client:
    def __init__(self, base: str):
        self.base = base.rstrip("/")
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def req(self, method: str, path: str, body=None, headers=None, timeout=120):
        h = {}
        data = None
        if isinstance(body, bytes):
            data = body
        elif body is not None:
            data = json.dumps(body).encode()
            h["Content-Type"] = "application/json"
        h.update(headers or {})
        r = self.op.open(urllib.request.Request(self.base + path, data=data, method=method, headers=h),
                         timeout=timeout)
        out = r.read().decode(errors="replace")
        return json.loads(out) if out else None

    def login(self, email: str, password: str) -> dict:
        self.req("POST", "/api/auth/login", {"email": email, "password": password})
        return self.req("GET", "/api/auth/me")

    def upload(self, path: Path, collection_id: int) -> dict:
        b = uuid.uuid4().hex
        body = (f"--{b}\r\nContent-Disposition: form-data; name=\"collection_id\"\r\n\r\n{collection_id}\r\n"
                f"--{b}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{path.name}\"\r\n"
                f"Content-Type: text/plain\r\n\r\n").encode() + path.read_bytes() + f"\r\n--{b}--\r\n".encode()
        return self.req("POST", "/api/documents/upload", body,
                        headers={"Content-Type": f"multipart/form-data; boundary={b}"})


def _as_list(value, key: str) -> list:
    if isinstance(value, dict):
        return value.get(key, [])
    return value or []


# ── Main flow ───────────────────────────────────────────────────────────────


class Log:
    def __init__(self, path: Path):
        self.path = path.expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def __call__(self, msg: str) -> None:
        line = f"{datetime.now(timezone.utc).isoformat(timespec='seconds')} {msg}"
        print(line)
        with self.path.open("a") as fh:
            fh.write(line + "\n")


def _env_path(name: str) -> Path | None:
    value = os.getenv(name)
    return Path(value) if value else None


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--url", default=os.getenv("GANTRY_SMOKE_URL"),
                   help="backend base URL (or env GANTRY_SMOKE_URL); required")
    p.add_argument("--admin-email", default=os.getenv("GANTRY_SMOKE_EMAIL", DEFAULT_ADMIN_EMAIL))
    p.add_argument("--admin-password-file", type=Path, default=_env_path("GANTRY_SMOKE_PASSWORD_FILE"),
                   help="file holding the admin password (or env GANTRY_SMOKE_PASSWORD_FILE); required")
    p.add_argument("--user-email", default=os.getenv("GANTRY_DEMO_USER_EMAIL", DEFAULT_USER_EMAIL))
    p.add_argument("--user-display-name", default=DEFAULT_USER_DISPLAY)
    p.add_argument("--user-password-file", type=Path, default=_env_path("GANTRY_DEMO_USER_PASSWORD_FILE"),
                   help="file holding the walkthrough user's password (or env GANTRY_DEMO_USER_PASSWORD_FILE)")
    p.add_argument("--admin-display-name", default=DEFAULT_ADMIN_DISPLAY)
    p.add_argument("--firm-name", default=DEFAULT_FIRM_NAME,
                   help="firm name GANTRY_DEMO_FIRM_NAME should show on the instance (checked, never set)")
    p.add_argument("--samples", type=Path, default=DEFAULT_SAMPLES)
    p.add_argument("--log", type=Path, default=Path(os.getenv("GANTRY_DEMO_SEED_LOG", "cpa_demo_seed.log")))
    p.add_argument("--apply", action="store_true", help="make the changes (default: dry run)")
    p.add_argument("--yes", action="store_true", help="allow a non-loopback target")
    args = p.parse_args(argv)
    if not args.url:
        p.error("--url (or env GANTRY_SMOKE_URL) is required")
    if not args.admin_password_file:
        p.error("--admin-password-file (or env GANTRY_SMOKE_PASSWORD_FILE) is required")
    return args


def run(args) -> int:  # noqa: C901 -- linear script flow
    log = Log(args.log)
    mode = "APPLY" if args.apply else "DRY-RUN"
    log(f"cpa_demo_seed {mode} target={args.url} admin={args.admin_email} user={args.user_email}")
    refusal = target_refusal(args.url, args.yes)
    if refusal:
        log("refused: " + refusal)
        return 2
    check_path_allowed(args.samples)
    samples = sample_files(args.samples)
    log(f"samples: {len(samples)} SAMPLE_*.txt in {args.samples}")

    admin = Client(args.url)
    cfg = admin.req("GET", "/api/config")
    if not (cfg or {}).get("demo_mode"):
        log("refused: target does not report demo_mode=true at /api/config; not a demo-mode instance")
        return 3
    firm = (cfg or {}).get("demo_firm_name", "")
    if firm != args.firm_name:
        log(f"warn: instance firm name is {firm!r}, expected {args.firm_name!r}; set GANTRY_DEMO_FIRM_NAME "
            "in the instance env (this script does not change instance config)")
    else:
        log(f"firm name ok: {firm!r}")
    me = admin.login(args.admin_email, read_secret(args.admin_password_file, "admin"))
    if me.get("role") != "admin":
        log(f"refused: {args.admin_email} is not an admin")
        return 4

    users = _as_list(admin.req("GET", "/api/admin/users"), "users")
    plan = plan_users(users, args.user_email, args.user_display_name, args.admin_email, args.admin_display_name)
    admin_threads = plan_threads(_as_list(admin.req("GET", "/api/chat/conversations"), "conversations"), "admin")
    plan.actions += admin_threads.actions
    admin_cols = plan_collections(_as_list(admin.req("GET", "/api/documents/collections"), "collections"), "admin")
    plan.warnings += admin_cols.warnings

    walk_exists = any(u["email"].lower() == args.user_email.lower() for u in users)
    user_pw = None
    if walk_exists or args.apply:
        if not args.user_password_file:
            log("refused: the walkthrough user's password file is required (--user-password-file or "
                "GANTRY_DEMO_USER_PASSWORD_FILE)")
            return 2
        user_pw = read_secret(args.user_password_file, "walkthrough user")
    walk = Client(args.url)
    col = None
    if walk_exists:
        walk.login(args.user_email, user_pw)
        plan.actions += plan_threads(_as_list(walk.req("GET", "/api/chat/conversations"), "conversations"),
                                     "user").actions
        cols = _as_list(walk.req("GET", "/api/documents/collections"), "collections")
        plan.warnings += plan_collections(cols, "user").warnings
        col = next((c for c in cols if c.get("name") == SAMPLE_COLLECTION), None)
        have = [d["filename"] for d in walk.req("GET", f"/api/documents?collection_id={col['id']}")] if col else []
        if col is None:
            plan.add("create_collection", owner="user", name=SAMPLE_COLLECTION)
        plan.actions += plan_samples(have, samples).actions
    else:
        plan.add("create_collection", owner="user", name=SAMPLE_COLLECTION)
        plan.actions += plan_samples([], samples).actions

    for a in plan.actions:
        log("plan: " + json.dumps(a, sort_keys=True))
    for w in plan.warnings:
        log("warn: " + w)
    if not plan.actions:
        log("nothing to do; instance already matches the demo seed")
    if not args.apply:
        log(f"dry run: {len(plan.actions)} change(s) planned, none made. Re-run with --apply.")
        return 0

    for a in plan.actions:
        kind = a["action"]
        if kind == "create_user":
            admin.req("POST", "/api/admin/users", {
                "email": a["email"], "password": user_pw, "display_name": a["display_name"], "role": "user",
            })
            walk.login(args.user_email, user_pw)
        elif kind == "update_user":
            body = {k: a[k] for k in ("display_name", "role") if k in a}
            admin.req("PATCH", f"/api/admin/users/{a['id']}", body)
        elif kind == "delete_thread":
            (admin if a["owner"] == "admin" else walk).req("DELETE", f"/api/chat/conversations/{a['id']}")
        elif kind == "create_collection":
            col = walk.req("POST", "/api/documents/collections", {"name": SAMPLE_COLLECTION})
        elif kind == "upload_sample":
            if col is None:
                raise SystemExit("no SAMPLE collection to upload into")
            d = walk.upload(args.samples / a["filename"], col["id"])
            a["status"] = d.get("status")
        log("done: " + json.dumps(a, sort_keys=True))
    log(f"applied {len(plan.actions)} change(s)")
    return 0


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        return run(args)
    except urllib.error.HTTPError as e:
        # Never echo request bodies (they may hold a password); status and path only.
        print(f"HTTP {e.code} from {urllib.parse.urlparse(e.url).path}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
