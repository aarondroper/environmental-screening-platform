# PAD-US audited staging repair

## Objective

Apply the owner-approved deterministic repair policy to the existing five-feature PAD-US raw sample, without modifying raw data or project source selection.

## Outcome

Verified the raw sample checksum before processing; applied Shapely 2.1.2 / GEOS 3.13.1 `make_valid` only to invalid shapes in derived staging; measured area in EPSG:5070; verified attributes and exact accounting of all five source features. Two valid source features were accepted unchanged. Three repaired candidates met validity, polygonality, nonempty, attribute, and area checks but were quarantined because interior-ring counts changed; one also gained a polygon component. The external QA report, accepted staging subset, and quarantine subset are listed in the manifest. FEMA remains an independent access blocker; Milestone 2 was not begun.
