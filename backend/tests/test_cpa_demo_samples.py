"""Hygiene checks on the synthetic CPA demo Client Files (scripts/fixtures/cpa_demo_samples)."""
import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SAMPLES = REPO / "scripts" / "fixtures" / "cpa_demo_samples"
FILES = sorted(SAMPLES.glob("SAMPLE_*.txt"))

SSN = re.compile(r"\b(\d{3})-(\d{2})-(\d{4})\b")
EIN = re.compile(r"(?<![\d-])(\d{2})-(\d{7})\b")
# Business names that could be real, retired from the corpus on purpose.
RETIRED_NAMES = ("lake" + "view", "tide" + "water", "harbor" + "view")  # built, so no literal in the repo
STREET_ADDRESS = re.compile(
    r"\b\d{1,5}\s+[A-Z][a-z]+(\s+[A-Z][a-z]+)?\s+(St|Street|Ave|Avenue|Rd|Road|Blvd|Dr|Drive|Ln|Lane|Way|Ct|Court)\b"
)
FICTIONAL_PAYERS = ("Sample Catering Co. (fictional)", "Example Card Payments Co. (fictional)",
                    "Sample Credit Union (fictional)")


def test_there_are_seven_sample_files():
    assert len(FILES) == 7


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_every_file_is_marked_synthetic_on_its_first_line(path):
    first = path.read_text().splitlines()[0]
    assert first.startswith("SYNTHETIC SAMPLE")
    assert "DEMO ONLY" in first


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_any_ssn_is_in_the_000_or_9xx_range_and_marked_fake(path):
    text = path.read_text()
    for area, _, _ in SSN.findall(text):
        assert area == "000" or area.startswith("9"), f"SSN area {area} in {path.name}"
    for line in text.splitlines():
        if SSN.search(line):
            assert "(fake)" in line


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_any_ein_is_in_a_9xx_style_range(path):
    for prefix, _ in EIN.findall(path.read_text()):
        assert prefix.startswith("9") or prefix == "00", f"EIN prefix {prefix} in {path.name}"


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_no_retired_business_names_and_no_street_addresses(path):
    text = path.read_text()
    for name in RETIRED_NAMES:
        assert name not in text.lower()
    assert not STREET_ADDRESS.search(text)


@pytest.mark.parametrize("path", [f for f in FILES if f.name in (
    "SAMPLE_document_requests_2026-11.txt", "SAMPLE_whitfield_2024_form1040_summary.txt",
    "SAMPLE_whitfield_2025_1099_summary.txt")], ids=lambda p: p.name)
def test_new_files_say_fictional_in_the_header_and_end_with_a_footer(path):
    lines = path.read_text().splitlines()
    assert "FICTIONAL" in lines[0]
    assert lines[-1] == "END OF SYNTHETIC SAMPLE - FICTIONAL - FOR DEMO ONLY"


def test_payers_are_the_clearly_fictional_names_in_every_file_that_mentions_them():
    text = {f.name: f.read_text() for f in FILES}
    assert all(p in text["SAMPLE_whitfield_2025_1099_summary.txt"] for p in FICTIONAL_PAYERS)
    assert "Sample Catering Co. (fictional)" in text["SAMPLE_whitfield_irs_cp2000_2024.txt"]
    assert "Sample Catering Co. (fictional)" in text["SAMPLE_document_requests_2026-11.txt"]
    assert "Sample Catering Co. (fictional)" in text["SAMPLE_whitfield_2024_form1040_summary.txt"]


def test_clients_map_to_the_cards_and_rehearsal_expectations():
    expected = json.loads((REPO / "scripts" / "fixtures" / "cpa_rehearsal_expected.json").read_text())
    requests = (SAMPLES / "SAMPLE_document_requests_2026-11.txt").read_text()
    for client in ("Whitfield", "Okafor", "Marisol Vega"):
        assert client in requests
    assert ["Vega"] in expected["cards"]["missing-documents"]["facts"]
    assert expected["cards"]["client-1099s"]["sources"] == ["SAMPLE_whitfield_2025_1099_summary.txt"]
    assert "Whitfield" in (SAMPLES / "SAMPLE_whitfield_2025_1099_summary.txt").read_text()
    assert "Whitfield" in (SAMPLES / "SAMPLE_whitfield_2024_form1040_summary.txt").read_text()


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_every_fictional_payer_mention_is_labeled(path):
    text = path.read_text()
    for bare in ("Sample Catering Co.", "Example Card Payments Co.", "Sample Credit Union"):
        assert text.count(bare) == text.count(f"{bare} (fictional)")


@pytest.mark.parametrize("name", ["SAMPLE_document_requests_2026-11.txt", "SAMPLE_whitfield_2024_form1040_summary.txt",
                                  "SAMPLE_whitfield_2025_1099_summary.txt"])
def test_new_files_label_the_bakery_as_fictional(name):
    assert "Harbor Lane Bakery LLC, fictional" in (SAMPLES / name).read_text() or \
        "Harbor Lane Bakery LLC (fictional)" in (SAMPLES / name).read_text()


def test_engagement_letter_header_says_fictional_not_real():
    lines = (SAMPLES / "SAMPLE_whitfield_engagement_letter_2025.txt").read_text().splitlines()
    assert "FICTIONAL / NOT REAL" in lines[0]
    assert lines[-1] == "END OF SYNTHETIC SAMPLE - FICTIONAL - FOR DEMO ONLY"


def _money(text: str, label: str) -> int:
    m = re.search(re.escape(label) + r"[^$\n]*\$([\d,]+)", text)
    assert m, f"no {label!r} line"
    return int(m.group(1).replace(",", ""))


def test_whitfield_2025_return_figures_are_internally_consistent():
    t = (SAMPLES / "SAMPLE_whitfield_2025_form1040_summary.txt").read_text()
    wages, interest = _money(t, "Line 1z wages"), _money(t, "Line 2b taxable interest")
    sch_c, total = _money(t, "Schedule C net profit"), _money(t, "Line 9 total income")
    adj, agi = _money(t, "Line 10 adjustments"), _money(t, "Line 11 adjusted gross income")
    std, taxable = _money(t, "Line 12 standard deduction"), _money(t, "Line 15 taxable income")
    assert interest == 212 and agi == 89_214
    assert std == 31_500  # 2025 MFJ standard deduction (OBBBA; IRS 2025 Form 1040 instructions)
    assert wages + interest + sch_c == total
    assert total - adj == agi
    assert agi - std == taxable
    one099 = (SAMPLES / "SAMPLE_whitfield_2025_1099_summary.txt").read_text()
    assert "$212 interest income" in one099


def test_whitfield_2024_return_figures_are_internally_consistent():
    t = (SAMPLES / "SAMPLE_whitfield_2024_form1040_summary.txt").read_text()
    total = _money(t, "Line 1z wages") + _money(t, "Schedule C net profit")
    assert total == _money(t, "Line 9 total income")
    agi = _money(t, "Line 11 adjusted gross income")
    assert total - _money(t, "Line 10 adjustments") == agi == 79_630
    assert agi - 29_200 == _money(t, "Line 15 taxable income")  # 2024 MFJ standard deduction
