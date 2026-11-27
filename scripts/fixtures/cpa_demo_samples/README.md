# CPA demo Client Files (synthetic)

Every file here is fictional demo data: no real client, taxpayer, firm or payer. SSNs are
`000-00-xxxx` and marked fake. Upload them into a collection named
`SAMPLE Clients (synthetic)` (the seed script, `scripts/cpa_demo_seed.py`, does this for
the walkthrough user).

- The first four (`okafor_2025_form1040_summary`, `whitfield_2025_form1040_summary`,
  `whitfield_engagement_letter_2025`, `whitfield_irs_cp2000_2024`) started as the corpus the demo
  instance already used (the demo's original sample directory). They have since been edited
  (fictional payer names, FICTIONAL markings, the 2025 return's Line 2b interest, adjustments
  and 2025 standard deduction), so they no longer match the copies on an older instance.
  `scripts/cpa_demo_seed.py` compares content, not just filenames, and plans a
  `replace_sample` for a same-named document whose content differs. See the live redeploy
  note in `docs/cpa-demo-mode.md` for removing the old CP2000 copy before reseeding.
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

Figures in the Whitfield returns are internally consistent: 2025 total income $94,692
($41,500 wages + $212 interest + $52,980 Schedule C) less $5,478 adjustments = AGI $89,214;
less the 2025 married-filing-jointly standard deduction of $31,500 (One, Big, Beautiful Bill
Act; IRS 2025 Form 1040 instructions, https://www.irs.gov/instructions/i1040gi) = taxable
income $57,714. 2024: $84,110 total income less $4,480 adjustments = AGI $79,630, less the
2024 standard deduction of $29,200 = $50,430. Tax, payment and refund lines are illustrative.
