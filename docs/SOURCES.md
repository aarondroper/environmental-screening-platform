# Sources

Region: Colorado (D3). Five owner-approved datasets (D4). Volumes are measured on the date
shown unless marked *estimate*. This records evidence, not legal advice; keep provider
citations and release identifiers with every snapshot.

| Source | Access pattern | Licence | Update behaviour | Colorado volume |
|---|---|---|---|---|
| **FEMA NFHL** — flood hazard zones (`S_FLD_HAZ_AR`) | ArcGIS REST MapServer, paginated query (`hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer`, flood hazard zones layer) | U.S. Government Works; keep FEMA attribution, DFIRM ID, effective dates | Continuous, community by community as LOMRs/new FIRMs become effective | 59,723 flood hazard polygons with `DFIRM_ID LIKE '08%'` in layer 28 (2026-09-27, from a US runner) |
| **PAD-US 4.1** — protected areas (Fee, Easement, Designation, Proclamation) | Versioned release; state geodatabase ZIP via ScienceBase `catalog/file/get/6759abcfd34edfeb8710a004?name=PADUS4_1_State_CO_GDB_KMZ.zip` | Public domain / CC0 (DOI 10.5066/P96WBCHS) | Major release roughly every 1–2 years | Colorado package 167,859,434 bytes (2026-09-27); ~14.5k features in the older v3.0 service |
| **Annual NLCD** — 2025 land cover, Collection 1.2 | OGC WCS GetCoverage (`dmsdata.cr.usgs.gov/geoserver/wcs`), EPSG:5070, 30 m | Public domain (DOI 10.5066/P143HE8T) | Annual release | *estimate* ~300 M cells, ~300 MB raw uint8 before COG compression |
| **USGS 3DEP 1 arc-second DEM** | TNM Access API → static GeoTIFF tiles on S3 (`prd-tnm.s3.amazonaws.com/StagedProducts/Elevation/1/TIFF/current/…`) | Public domain | Tiles republished as new lidar is incorporated (`Last-Modified` per tile) | 28 one-degree tiles, ~43–52 MB each, ~1.3 GB (2026-09-27) |
| **NRCS SSURGO** — map units + component hydric rating | Soil Data Access SQL/REST (`SDMDataAccess.sc.egov.usda.gov/Tabular/post.rest`) and per-survey-area ZIP packages (Web Soil Survey) | Public domain | Annual refresh (each October) plus ad-hoc survey updates (`saverest` per survey area) | 78 survey areas, 7,740 map units, 478,106 polygons (2026-09-27) |

Region boundary: 2025 Census TIGER/Line state boundary for Colorado (STATEFP 08), public domain.

## Known access issues

- **Geo-restriction:** `hazards.fema.gov`, `msc.fema.gov`, and `www.sciencebase.gov` reset
  or challenge non-US traffic, but served a GitHub-hosted US runner normally on 2026-09-27.
  Live ingestion must run from US infrastructure.
- **FEMA:** Esri's Living Atlas copy is a derivative under Esri terms; do not substitute it.
  Unmapped or unstudied areas are *unknown*, never "no flood hazard".
- **PAD-US:** Use the documented `catalog/file/get` route. The `sciencebase.usgs.gov/manager`
  download links are a JavaScript app and the backing S3 object is private (403). The
  anonymous USGS feature services still serve **v3.0**; do not use them. Some features have
  invalid geometry, so repairs happen in staging only and are recorded. Overlapping
  categories can double-count area, so metrics report per category.
- **SSURGO:** ~10 invalid source polygons were found across 19 Northern Colorado packages;
  `ST_MakeValid` in staging, with originals kept. Hydric rating is a soil indicator, never a
  wetland determination. Survey areas cross state lines; clip to the region.
- **NLCD:** Class 90/95 (wetlands) are land-cover classes, not wetland determinations. A
  statewide WCS request likely needs to be tiled into windows.
- **3DEP:** Units metres, NAVD88. Slope is computed in a projected CRS (EPSG:5070).
