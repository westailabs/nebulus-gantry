"""Tests for the GANTRY_DEMO_MODE flag and GET /api/config (CPA demo mode, issue 0)."""

import pytest
from fastapi.testclient import TestClient

from backend.config import Settings, settings
from backend.main import app

client = TestClient(app)


@pytest.fixture
def demo_settings(monkeypatch):
    """Patch the live settings object the router reads; restored after each test."""

    def _set(demo_mode: bool, firm: str = ""):
        monkeypatch.setattr(settings, "demo_mode", demo_mode)
        monkeypatch.setattr(settings, "demo_firm_name", firm)

    return _set


class TestDemoModeSetting:
    @pytest.mark.parametrize("raw", ["true", "TRUE", "1", "yes", " Yes "])
    def test_truthy_values_enable(self, monkeypatch, raw):
        monkeypatch.setenv("GANTRY_DEMO_MODE", raw)
        assert Settings().demo_mode is True

    @pytest.mark.parametrize("raw", ["", "false", "0", "no", "off", "demo"])
    def test_other_values_disable(self, monkeypatch, raw):
        monkeypatch.setenv("GANTRY_DEMO_MODE", raw)
        assert Settings().demo_mode is False

    def test_default_is_off(self, monkeypatch):
        monkeypatch.delenv("GANTRY_DEMO_MODE", raising=False)
        assert Settings().demo_mode is False

    def test_firm_name_trimmed_and_empty_by_default(self, monkeypatch):
        monkeypatch.delenv("GANTRY_DEMO_FIRM_NAME", raising=False)
        assert Settings().demo_firm_name == ""
        monkeypatch.setenv("GANTRY_DEMO_FIRM_NAME", "  Sample & Co. CPAs ")
        assert Settings().demo_firm_name == "Sample & Co. CPAs"


class TestConfigEndpoint:
    def test_flag_off_by_default_shape(self, demo_settings):
        demo_settings(False)
        resp = client.get("/api/config")
        assert resp.status_code == 200
        assert resp.json() == {"demo_mode": False, "demo_firm_name": ""}

    def test_flag_on_with_firm_name(self, demo_settings):
        demo_settings(True, "Sample & Co. CPAs")
        resp = client.get("/api/config")
        assert resp.json() == {"demo_mode": True, "demo_firm_name": "Sample & Co. CPAs"}

    def test_firm_name_empty_when_unset(self, demo_settings):
        demo_settings(True, "")
        assert client.get("/api/config").json()["demo_firm_name"] == ""

    def test_no_auth_required_and_read_only(self, demo_settings):
        demo_settings(True)
        assert client.get("/api/config").status_code == 200
        assert client.post("/api/config", json={"demo_mode": False}).status_code == 405
        assert settings.demo_mode is True

    def test_exposes_only_ui_switches(self, demo_settings):
        demo_settings(True, "Sample & Co. CPAs")
        assert set(client.get("/api/config").json()) == {"demo_mode", "demo_firm_name"}
