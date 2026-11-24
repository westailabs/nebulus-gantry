"""PR #6 review fixes, ported from Plumb's repros (former test_FINDING_* cases now assert
the fixed behaviour). Keys are throwaway keys in tmp dirs; no real key file is read."""
import fnmatch
import importlib.util
import logging
import multiprocessing as mp
import os
import pathlib
import stat

import pytest

from backend.services import secret_key_manager as skm

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _smoke():
    spec = importlib.util.spec_from_file_location("smoke", ROOT / "scripts/cpa_demo_smoke.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# ── S1: build contexts exclude data/, key files, DBs, env files ────────────
def _patterns(path):
    return [ln.strip() for ln in path.read_text().splitlines() if ln.strip() and not ln.startswith("#")]


def _excluded(rel, patterns):
    """Approximate Docker's .dockerignore matching (enough for these patterns)."""
    for p in patterns:
        p = p.rstrip("/")
        variants = {p, p.removeprefix("**/")}
        for v in variants:
            parts = rel.split("/")
            # match the path itself or any parent directory
            for i in range(1, len(parts) + 1):
                if fnmatch.fnmatch("/".join(parts[:i]), v) or fnmatch.fnmatch(parts[i - 1], v):
                    return True
    return False


@pytest.mark.parametrize("ignore_file,context_paths", [
    ("backend/.dockerignore", ["data/.secret_key", "data/.secret_key_tmp_ab12", "data/gantry.db",
                               "gantry.db", ".env", ".env.local", "services/__pycache__/x.pyc"]),
    (".dockerignore", ["data/.secret_key", "backend/data/.secret_key", "data/gantry.db",
                       "backend/.secret_key", ".env"]),
])
def test_build_context_excludes_secrets_and_data(ignore_file, context_paths):
    patterns = _patterns(ROOT / ignore_file)
    for rel in context_paths:
        assert _excluded(rel, patterns), (ignore_file, rel)


def test_backend_context_keeps_source():
    patterns = _patterns(ROOT / "backend/.dockerignore")
    for rel in ("main.py", "requirements.txt", "services/secret_key_manager.py", "routers/chat.py"):
        assert not _excluded(rel, patterns), rel


# ── S2: exclusive key creation; concurrent first start agrees on one key ────
def _worker(d, barrier, q):
    barrier.wait()
    q.put(skm.get_secret_key(pathlib.Path(d)))


def test_multiworker_first_start_single_key(tmp_path):
    ctx = mp.get_context("fork")
    for i in range(25):
        d = tmp_path / f"r{i}"
        d.mkdir()
        n = 10
        barrier, q = ctx.Barrier(n), ctx.Queue()
        ps = [ctx.Process(target=_worker, args=(str(d), barrier, q)) for _ in range(n)]
        [p.start() for p in ps]
        keys = [q.get(timeout=30) for _ in range(n)]
        [p.join() for p in ps]
        final = (d / ".secret_key").read_text().strip()
        assert set(keys) == {final}
        assert not list(d.glob(".secret_key_tmp_*"))


def test_key_file_0600_hex_64_persisted(tmp_path):
    k = skm.get_secret_key(tmp_path)
    assert stat.S_IMODE((tmp_path / ".secret_key").stat().st_mode) == 0o600
    assert len(k) == 64 and skm.get_secret_key(tmp_path) == k


def test_rotate_still_overwrites(tmp_path):
    k = skm.get_secret_key(tmp_path)
    assert skm.rotate_secret_key(tmp_path) != k


def test_empty_existing_file_is_replaced(tmp_path):
    (tmp_path / ".secret_key").write_text("")
    k = skm.get_secret_key(tmp_path)
    assert len(k) == 64 and (tmp_path / ".secret_key").read_text().strip() == k


# ── Nits: env strip/short warn, read-only dir hint, loose perms, repr ───────
def test_whitespace_env_key_treated_as_unset(tmp_path, monkeypatch):
    from backend import config
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setenv("SECRET_KEY", "   ")
    assert len(config._get_secret_key()) == 64 and (tmp_path / ".secret_key").exists()


def test_short_env_key_warns(tmp_path, monkeypatch, caplog):
    from backend import config
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setenv("SECRET_KEY", "  abc  ")
    with caplog.at_level(logging.WARNING):
        assert config._get_secret_key() == "abc"
    msgs = [r.getMessage() for r in caplog.records]
    assert any("SECRET_KEY" in m and "32" in m for m in msgs)
    assert all("abc" not in m for m in msgs)


def test_readonly_data_dir_gives_hint(tmp_path):
    if os.geteuid() == 0:
        pytest.skip("root ignores dir perms")
    ro = tmp_path / "ro"
    ro.mkdir()
    ro.chmod(0o555)
    try:
        with pytest.raises(RuntimeError) as e:
            skm.get_secret_key(ro)
        assert "SECRET_KEY" in str(e.value) and "GANTRY_DATA_DIR" in str(e.value)
    finally:
        ro.chmod(0o755)


def test_world_readable_key_warns(tmp_path, caplog):
    f = tmp_path / ".secret_key"
    f.write_text("a" * 64)
    f.chmod(0o644)
    with caplog.at_level(logging.WARNING):
        assert skm.get_secret_key(tmp_path) == "a" * 64
    msgs = [r.getMessage() for r in caplog.records]
    assert any("0600" in m for m in msgs) and all("a" * 64 not in m for m in msgs)


def test_settings_repr_hides_key(tmp_path, monkeypatch):
    from backend import config
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setenv("SECRET_KEY", "k" * 40)
    assert "k" * 40 not in repr(config.Settings())


# ── Nit: calibrate fails loudly when search returns nothing ─────────────────
def test_calibrate_exits_when_search_returns_nothing(monkeypatch, capsys):
    s = _smoke()
    monkeypatch.setattr(s, "req", lambda m, p, *a, **k: (
        [{"id": 4, "name": "SAMPLE Clients x"}] if p.endswith("collections") else {"results": []}))
    with pytest.raises(SystemExit) as e:
        s.calibrate()
    assert e.value.code not in (0, None) and "Chroma" in str(e.value)


# ── Nit: audit detail prep failure must not raise into the request ─────────
def test_audit_prep_failure_is_swallowed(monkeypatch):
    from backend.services import audit_service
    from backend.services.audit_service import AuditService

    class Bad:
        def __iter__(self):
            raise ValueError("boom")

        def keys(self):
            raise ValueError("boom")

    monkeypatch.setattr(audit_service, "write_failures", 0)
    AuditService(db=None).record("x.y", detail=Bad())  # must not raise
    assert audit_service.write_failures == 1


# ── os.link fallback for filesystems without hard links ────────────────────
def _no_link(*a, **k):
    import errno
    raise OSError(errno.EPERM, "Operation not permitted")


def test_link_eperm_falls_back_to_excl_open(tmp_path, monkeypatch):
    monkeypatch.setattr(skm.os, "link", _no_link)
    k = skm.get_secret_key(tmp_path)
    f = tmp_path / ".secret_key"
    assert len(k) == 64 and stat.S_IMODE(f.stat().st_mode) == 0o600
    assert skm.get_secret_key(tmp_path) == k and f.read_text().strip() == k
    assert not list(tmp_path.glob(".secret_key_tmp_*"))


def test_fallback_existing_file_returns_existing_key(tmp_path, monkeypatch):
    monkeypatch.setattr(skm.os, "link", _no_link)
    f = tmp_path / ".secret_key"
    f.write_text("b" * 64)
    f.chmod(0o600)
    assert skm._create_key_exclusive(f, "c" * 64) is None
    assert skm.get_secret_key(tmp_path) == "b" * 64


def test_fallback_failure_raises_storage_error(tmp_path, monkeypatch):
    import errno
    monkeypatch.setattr(skm.os, "link", _no_link)
    real_open = skm.os.open

    def bad_open(path, flags, *a, **k):
        if str(path).endswith(".secret_key"):
            raise OSError(errno.EROFS, "Read-only file system")
        return real_open(path, flags, *a, **k)
    monkeypatch.setattr(skm.os, "open", bad_open)
    with pytest.raises(RuntimeError) as e:
        skm.get_secret_key(tmp_path)
    assert "SECRET_KEY" in str(e.value)
    assert not (tmp_path / ".secret_key").exists()
    assert not list(tmp_path.glob(".secret_key_tmp_*"))


def test_fallback_concurrent_workers_agree(tmp_path, monkeypatch):
    monkeypatch.setattr(skm.os, "link", _no_link)  # inherited by forked workers
    ctx = mp.get_context("fork")
    for i in range(10):
        d = tmp_path / f"f{i}"
        d.mkdir()
        n = 8
        barrier, q = ctx.Barrier(n), ctx.Queue()
        ps = [ctx.Process(target=_worker, args=(str(d), barrier, q)) for _ in range(n)]
        [p.start() for p in ps]
        keys = [q.get(timeout=30) for _ in range(n)]
        [p.join() for p in ps]
        assert set(keys) == {(d / ".secret_key").read_text().strip()}
