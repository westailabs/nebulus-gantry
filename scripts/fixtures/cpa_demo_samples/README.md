# CPA demo Client Files (synthetic)

Every file here is fictional demo data: no real client, taxpayer, firm or payer. SSNs are
`000-00-xxxx` and marked fake. Upload them into a collection named
`SAMPLE Clients (synthetic)` (the seed script, `scripts/cpa_demo_seed.py`, does this for
the walkthrough user).

- The first four (`okafor_2025_form1040_summary`, `whitfield_2025_form1040_summary`,
  `whitfield_engagement_letter_2025`, `whitfield_irs_cp2000_2024`) are the corpus the demo
  instance already used (`~/demo/gantry-cpa-samples`). Three are byte-identical to it. The
  CP2000 differs in one name: payer "Lakeview Catering Inc." became "Sample Catering Co.",
  because a real-sounding business name has no place in a synthetic file.
- Three were added so every CPA starter card has a document to cite:
  `document_requests_2026-11` (missing documents), `whitfield_2025_1099_summary`
  (1099s) and `whitfield_2024_form1040_summary` (year-over-year).

The engagement letter stays in the corpus as a document, but there is no
engagement-letter starter card. Adding documents can move retrieval similarities, so
re-run `scripts/cpa_demo_smoke.py calibrate` after uploading them.

Rules, enforced by `backend/tests/test_cpa_demo_samples.py`: line 1 of every file says
`SYNTHETIC SAMPLE ... FOR DEMO ONLY`; any SSN is `000-` (or `9xx-`) and marked `(fake)`; any
EIN starts with 9; payers use obviously fictional names (Sample Catering Co., Example Card
Payments Co., Sample Credit Union); no street addresses; the three newer files also say
`FICTIONAL` in the header and end with a footer line.
