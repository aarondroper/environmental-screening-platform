# Screening workspace usability pass

## Outcome

Implemented a focused information-hierarchy pass on the primary screening
workspace. The shell and project header are shorter; the map remains dominant;
the layer control is compact/collapsible with an AOI visibility toggle; and the
source summary is a five-row expandable list with observed metrics inline.
Hashes, source IDs, checksums, and operational detail are not shown in the
primary view and remain available through the secondary data-source, reports,
activity, and operations views.

Validation completed:

- frontend tests: 19 passed;
- production build: passed;
- manual desktop and mobile browser review: completed with the recorded AOI
  visible over the attributed basemap;
- Python behavior, source semantics, operations route, and exports unchanged.
