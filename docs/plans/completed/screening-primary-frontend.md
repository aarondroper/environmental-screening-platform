# Primary environmental screening view

## Objective

Make the recorded Washington, DC screening result the primary static frontend
experience while retaining the existing report-audit console as a secondary
technical view.

## Scope

- Render the checked-in AOI polygon and recorded source metrics without adding
  provider access, processing, or new analytical semantics.
- Preserve explicit incomplete, unavailable, blocked, conditional, unknown,
  and nodata states and source provenance disclosures.
- Keep JSON export available and identify fixture outputs that are not present.
- Add focused frontend tests and update the frontend README guidance.

## Outcome

Completed 2026-09-26. The primary route now renders the exact recorded
Washington, DC AOI polygon, independent source metrics and status semantics,
provenance disclosures, limitations, and the available JSON report export.
`?view=operations` retains the technical lifecycle report as a secondary view.
No backend, provider access, new source processing, or screening behavior was
added. Frontend tests and the production build passed.
