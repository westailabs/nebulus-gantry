# CPA demo Client Files (synthetic)

Every file here is fictional demo data: no real client, taxpayer, firm or payer. SSNs are
`000-00-xxxx` and marked fake. Upload them into a collection named
`SAMPLE Clients (synthetic)` (the seed script, `scripts/cpa_demo_seed.py`, does this for
the walkthrough user).

- The first four (`okafor_2025_form1040_summary`, `whitfield_2025_form1040_summary`,
  `whitfield_engagement_letter_2025`, `whitfield_irs_cp2000_2024`) are byte-for-byte the
  corpus the demo instance already used (`~/demo/gantry-cpa-samples`).
- Three were added so every CPA starter card has a document to cite:
  `document_requests_2026-11` (missing documents), `whitfield_2025_1099_summary`
  (1099s) and `whitfield_2024_form1040_summary` (year-over-year).

The engagement letter stays in the corpus as a document, but there is no
engagement-letter starter card. Adding documents can move retrieval similarities, so
re-run `scripts/cpa_demo_smoke.py calibrate` after uploading them.
