"""CPA demo mode, issue 5: scripts/cpa_demo_seed.py planning and an API round trip
against the real app (TestClient), with document upload stubbed (no Chroma)."""
import importlib.util
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from backend.config import settings  # noqa: E402
from backend.database import Base  # noqa: E402
from backend.dependencies import get_db  # noqa: E402
from backend.main import app  # noqa: E402
from backend.models.conversation import Conversation  # noqa: E402
from backend.models.user import User  # noqa: E402
from backend.services.auth_service import AuthService  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("cpa_demo_seed", REPO / "scripts" / "cpa_demo_seed.py")
seed = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("cpa_demo_seed", seed)
_spec.loader.exec_module(seed)

ADMIN_PW = "admin-pw-123456"
USER_PW = "sarah-pw-123456"


# ── pure helpers ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("title,leftover", [
    # known leftover titles and prefixes
    ("Moto test", True), ("moto TEST 2", True), ("moto", True), ("Smoke run", True), ("probe 3", True),
    ("Tests", True), ("Testing", True), ("test", True), ("test 3", True), ("Debug", True), ("debug 2", True),
    # real work that merely contains the words must survive
    ("safe-harbor test", False), ("Safe harbor test for Whitfield", False), ("Okafor debug notes", False),
    ("Whitfield CP2000 question", False), ("Okafor 2025 return", False), ("Testing citations", False),
    ("Attestation letter", False), ("attestation", False), ("Contest", False), ("contested deduction", False),
    ("Contest results", False), ("Latest filing status", False), ("Protest letter", False),
    ("Testimony prep", False), ("Debugging notes for Okafor", False), ("Probed amounts", False),
    ("Motorcycle dealer return", False), ("Smoker deduction question", False), ("Attest test", False),
])
def test_leftover_titles(title, leftover):
    assert seed.is_leftover_title(title) is leftover


def test_plan_users_creates_non_admin_sarah_and_renames_demo_admin():
    users = [{"id": 1, "email": "admin@gantry-demo.example.com", "display_name": "Demo Admin", "role": "admin"}]
    plan = seed.plan_users(users, seed.DEFAULT_USER_EMAIL, "Sarah Chen, CPA",
                           "admin@gantry-demo.example.com", "Setup Admin")
    assert {"action": "create_user", "email": seed.DEFAULT_USER_EMAIL, "display_name": "Sarah Chen, CPA",
            "role": "user"} in plan.actions
    assert {"action": "update_user", "id": 1, "email": "admin@gantry-demo.example.com",
            "display_name": "Setup Admin"} in plan.actions


def test_plan_users_demotes_and_renames_existing_walkthrough_user():
    users = [{"id": 2, "email": seed.DEFAULT_USER_EMAIL, "display_name": "Demo Admin", "role": "admin"}]
    plan = seed.plan_users(users, seed.DEFAULT_USER_EMAIL, "Sarah Chen, CPA", "admin@x.example.com", "Setup Admin")
    assert plan.actions == [{"action": "update_user", "id": 2, "email": seed.DEFAULT_USER_EMAIL,
                             "display_name": "Sarah Chen, CPA", "role": "user"}]


def test_plan_users_noop_when_already_seeded():
    users = [{"id": 1, "email": "admin@gantry-demo.example.com", "display_name": "Setup Admin", "role": "admin"},
             {"id": 2, "email": seed.DEFAULT_USER_EMAIL, "display_name": "Sarah Chen, CPA", "role": "user"}]
    assert seed.plan_users(users, seed.DEFAULT_USER_EMAIL, "Sarah Chen, CPA",
                           "admin@gantry-demo.example.com", "Setup Admin").actions == []


def test_plan_samples_only_uploads_missing(tmp_path):
    files = [tmp_path / "SAMPLE_a.txt", tmp_path / "SAMPLE_b.txt"]
    plan = seed.plan_samples(["SAMPLE_a.txt"], files)
    assert plan.actions == [{"action": "upload_sample", "filename": "SAMPLE_b.txt"}]


def test_plan_collections_warns_on_non_synthetic_names():
    plan = seed.plan_collections([{"id": 1, "name": "SAMPLE Clients (synthetic)"},
                                  {"id": 2, "name": "Acme Holdings"}], "user")
    assert len(plan.warnings) == 1 and "Acme Holdings" in plan.warnings[0]


def test_checked_in_samples_are_all_synthetic():
    files = seed.sample_files(seed.DEFAULT_SAMPLES)
    assert len(files) >= 7
    for f in files:
        assert f.name.startswith("SAMPLE_")
        assert "SYNTHETIC SAMPLE" in f.read_text().splitlines()[0]


def test_refuses_files_in_the_other_gantry_checkout(monkeypatch, tmp_path):
    other = tmp_path / "other-checkout"
    other.mkdir(parents=True)
    monkeypatch.setattr(seed, "FORBIDDEN_ROOTS", (other,))
    with pytest.raises(SystemExit):
        seed.check_path_allowed(other / "secrets" / "admin_password")


# ── round trip through the real API ─────────────────────────────────────────


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    yield Session
    app.dependency_overrides.pop(get_db, None)
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


class FakeClient(seed.Client):
    """seed.Client over FastAPI's TestClient; uploads are recorded, not indexed."""

    uploads: list = []
    collections: dict = {}

    def __init__(self, base):
        super().__init__(base)
        self.tc = TestClient(app)

    def req(self, method, path, body=None, headers=None, timeout=120):
        if path.startswith("/api/documents"):
            return self._documents(method, path, body)
        r = self.tc.request(method, path, json=body)
        if r.status_code >= 400:
            raise AssertionError(f"{method} {path} -> {r.status_code} {r.text}")
        return r.json() if r.text else None

    def _documents(self, method, path, body):
        me = self.tc.get("/api/auth/me").json()["id"]
        if path == "/api/documents/collections" and method == "GET":
            return [c for c in FakeClient.collections.values() if c["user_id"] == me]
        if path == "/api/documents/collections" and method == "POST":
            cid = len(FakeClient.collections) + 1
            FakeClient.collections[cid] = {"id": cid, "user_id": me, "name": body["name"]}
            return FakeClient.collections[cid]
        if path.startswith("/api/documents?collection_id="):
            cid = int(path.split("=")[1])
            return [{"filename": u["filename"]} for u in FakeClient.uploads if u["collection_id"] == cid]
        raise AssertionError(path)

    def upload(self, path, collection_id):
        FakeClient.uploads.append({"filename": path.name, "collection_id": collection_id})
        return {"status": "ready"}


@pytest.fixture
def instance(db_session, monkeypatch, tmp_path):
    db = db_session()
    auth = AuthService(db)
    admin = auth.create_user(email="admin@gantry-demo.example.com", password=ADMIN_PW,
                             display_name="Demo Admin", role="admin")
    db.add_all([Conversation(user_id=admin.id, title="Moto test"),
                Conversation(user_id=admin.id, title="Setup notes")])
    db.commit()
    db.close()
    (tmp_path / "admin_pw").write_text(ADMIN_PW + "\n")
    (tmp_path / "user_pw").write_text(USER_PW + "\n")
    monkeypatch.setattr(seed, "Client", FakeClient)
    monkeypatch.setattr(settings, "demo_mode", True)
    FakeClient.uploads = []
    FakeClient.collections = {}
    return tmp_path


def _argv(tmp_path, *extra):
    return ["--url", "http://127.0.0.1:9", "--admin-password-file", str(tmp_path / "admin_pw"), "--user-password-file", str(tmp_path / "user_pw"),
            "--log", str(tmp_path / "seed.log"), *extra]


def test_dry_run_changes_nothing_and_logs_plan(instance, db_session):
    assert seed.main(_argv(instance)) == 0
    db = db_session()
    assert db.query(User).count() == 1
    assert db.query(User).one().display_name == "Demo Admin"
    assert db.query(Conversation).count() == 2
    log = (instance / "seed.log").read_text()
    assert "DRY-RUN" in log and '"create_user"' in log and '"delete_thread"' in log
    assert FakeClient.uploads == []


def test_apply_seeds_and_is_idempotent(instance, db_session, capsys):
    assert seed.main(_argv(instance, "--apply")) == 0
    db = db_session()
    sarah = db.query(User).filter_by(email=seed.DEFAULT_USER_EMAIL).one()
    assert (sarah.display_name, sarah.role) == ("Sarah Chen, CPA", "user")
    admin = db.query(User).filter_by(email="admin@gantry-demo.example.com").one()
    assert admin.display_name == "Setup Admin" and admin.role == "admin"
    assert [c.title for c in db.query(Conversation)] == ["Setup notes"]
    names = sorted(u["filename"] for u in FakeClient.uploads)
    assert names == sorted(f.name for f in seed.sample_files(seed.DEFAULT_SAMPLES))
    assert [c["name"] for c in FakeClient.collections.values()] == [seed.SAMPLE_COLLECTION]
    db.close()

    # second run: nothing left to do
    assert seed.main(_argv(instance, "--apply")) == 0
    assert len(FakeClient.uploads) == len(names)
    assert "nothing to do" in (instance / "seed.log").read_text().splitlines()[-2]

    # passwords never reach stdout or the log
    out = capsys.readouterr().out + (instance / "seed.log").read_text()
    assert ADMIN_PW not in out and USER_PW not in out


def test_refuses_when_target_is_not_in_demo_mode(instance, monkeypatch, db_session):
    monkeypatch.setattr(settings, "demo_mode", False)
    assert seed.main(_argv(instance, "--apply")) == 3
    assert db_session().query(User).count() == 1


def test_refuses_non_loopback_without_yes(instance):
    assert seed.main(_argv(instance)[2:] + ["--url", "http://10.0.0.5:9000"]) == 2
    assert "refused" in (instance / "seed.log").read_text()


def test_non_loopback_with_yes_still_needs_https(instance):
    argv = _argv(instance)[2:]
    assert seed.main(argv + ["--url", "http://10.0.0.5:9000", "--yes"]) == 2
    assert "must use https" in (instance / "seed.log").read_text()
    assert seed.target_refusal("https://demo.example.org", True) is None
    assert seed.target_refusal("https://demo.example.org", False) is not None
    assert seed.target_refusal("http://127.0.0.1:9", False) is None


def test_url_and_admin_password_file_are_required_not_defaulted(monkeypatch, tmp_path):
    for name in ("GANTRY_SMOKE_URL", "GANTRY_SMOKE_PASSWORD_FILE", "GANTRY_DEMO_USER_PASSWORD_FILE"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(SystemExit):
        seed.parse_args(["--admin-password-file", str(tmp_path / "x")])
    with pytest.raises(SystemExit):
        seed.parse_args(["--url", "http://127.0.0.1:9"])
    ns = seed.parse_args(["--url", "http://127.0.0.1:9", "--admin-password-file", str(tmp_path / "x")])
    assert ns.user_password_file is None


HOST_SPECIFIC = ("80" + "13", "." + "secrets", "." + "nebulus", "nebulus" + "-gantry", "demo/" + "gantry-cpa")


def test_no_host_specific_paths_or_ports_are_baked_into_the_scripts():
    for name in ("cpa_demo_seed.py", "cpa_demo_rehearse.py"):
        text = (REPO / "scripts" / name).read_text()
        for needle in ("8013", "secrets", ".nebulus", "nebulus-gantry", "/Users/", "/home/", "demo/gantry-cpa"):
            assert needle not in text, f"{needle!r} in {name}"
    docs = (REPO / "docs" / "cpa-demo-mode.md").read_text()
    for needle in ("8013", "secrets", ".nebulus", "nebulus-gantry", "demo/gantry-cpa"):
        assert needle not in docs


def test_log_lines_are_json_parsable_plan_entries(instance):
    seed.main(_argv(instance))
    plans = [json.loads(line.split("plan: ", 1)[1]) for line in (instance / "seed.log").read_text().splitlines()
             if " plan: " in line]
    assert {p["action"] for p in plans} >= {"create_user", "update_user", "delete_thread", "upload_sample"}


def test_default_firm_name_is_sample_and_co_cpas():
    assert seed.DEFAULT_FIRM_NAME == "Sample & Co. CPAs"
    env_example = (REPO / ".env.example").read_text()
    assert 'GANTRY_DEMO_FIRM_NAME="Sample & Co. CPAs"' in env_example


def test_seed_warns_when_the_instance_firm_name_differs_and_does_not_change_it(instance, monkeypatch):
    monkeypatch.setattr(settings, "demo_firm_name", "")
    assert seed.main(_argv(instance)) == 0
    assert "warn: instance firm name is ''" in (instance / "seed.log").read_text()
    assert settings.demo_firm_name == ""


def test_seed_reports_ok_when_the_firm_name_matches(instance, monkeypatch):
    monkeypatch.setattr(settings, "demo_firm_name", "Sample & Co. CPAs")
    assert seed.main(_argv(instance)) == 0
    log = (instance / "seed.log").read_text()
    assert "firm name ok: 'Sample & Co. CPAs'" in log and "warn: instance firm name" not in log


def test_dry_run_lists_exactly_the_threads_it_would_delete_and_deletes_none(instance, db_session):
    db = db_session()
    admin = db.query(User).one()
    db.add_all([Conversation(user_id=admin.id, title="Attestation prep"),
                Conversation(user_id=admin.id, title="Contest notes")])
    db.commit()
    db.close()
    assert seed.main(_argv(instance)) == 0
    plans = [json.loads(line.split("plan: ", 1)[1]) for line in (instance / "seed.log").read_text().splitlines()
             if " plan: " in line]
    deletes = [p for p in plans if p["action"] == "delete_thread"]
    assert [(d["owner"], d["title"]) for d in deletes] == [("admin", "Moto test")]
    assert db_session().query(Conversation).count() == 4  # nothing deleted


def test_apply_only_touches_admin_and_sarah_threads(instance, db_session):
    db = db_session()
    bob = AuthService(db).create_user(email="bob@example.com", password="bob-pw-123456",
                                      display_name="Bob", role="user")
    admin = db.query(User).filter_by(email="admin@gantry-demo.example.com").one()
    db.add_all([Conversation(user_id=bob.id, title="Moto test"),
                Conversation(user_id=admin.id, title="Attestation prep"),
                Conversation(user_id=admin.id, title="Contest notes")])
    db.commit()
    db.close()
    assert seed.main(_argv(instance, "--apply")) == 0
    db = db_session()
    titles = sorted((db.get(User, c.user_id).email, c.title) for c in db.query(Conversation))
    assert titles == [("admin@gantry-demo.example.com", "Attestation prep"),
                      ("admin@gantry-demo.example.com", "Contest notes"),
                      ("admin@gantry-demo.example.com", "Setup notes"),
                      ("bob@example.com", "Moto test")]
