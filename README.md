# GeoMeasure API

A production-style FastAPI backend that accepts geospatial files (KML, or ZIP
archives containing a Shapefile), extracts their features, detects the source
Coordinate Reference System (CRS), projects the data to a suitable metric CRS
and reports **real measurements** — polygon area in m² and line length in m —
per feature.

No measurements are faked: every value is computed with `pyproj`/`shapely`
after an explicit CRS transformation, and when a correct measurement is not
possible the API says so with a status instead of guessing.

---

## Table of Contents

- [Project Overview](#project-overview)
- [Features](#features)
- [Architecture](#architecture)
- [Project Structure](#project-structure)
- [Setup and Installation](#setup-and-installation)
- [Running the Application](#running-the-application)
- [API Reference](#api-reference)
- [Interactive Documentation](#interactive-documentation)
- [CRS Strategy](#crs-strategy)
- [Error Handling](#error-handling)
- [Security](#security)
- [Testing](#testing)
- [Design Decisions](#design-decisions)
- [Learning](#learning)
- [Future Scope](#future-scope)
- [Limitations](#limitations)

---

## Project Overview

Geospatial files arrive in many dialects: KML always stores coordinates in
GPS longitude/latitude (EPSG:4326, decimal degrees), Shapefiles carry their
own CRS description in a `.prj` sidecar (or none at all), and some datasets
are already projected. Measuring a polygon directly in degrees produces
meaningless numbers, and measuring in Web Mercator inflates them.

GeoMeasure API solves this with an explicit pipeline:

1. **Ingest** the upload with strict validation (extension, size, magic bytes).
2. **Parse** features with a real geospatial reader (pyogrio, falling back to fiona).
3. **Detect** the source CRS; never silently assume one.
4. **Choose** a metric measurement CRS: reuse a valid projected source CRS, or
   automatically select the UTM zone covering the data.
5. **Transform** every geometry with `pyproj`.
6. **Measure** area/length with `shapely` in the transformed CRS and persist
   the result in SQLite.
7. **Serve** the outcome through read endpoints with structured errors.

## Features

- `POST /api/files/` — upload a `.kml` or `.zip` (Shapefile) and process it synchronously.
- `GET /health` — liveness probe.
- `GET /api/files/{id}/` — metadata plus every extracted feature (GeoJSON geometry, properties, CRS).
- `GET /api/files/{id}/measurements/` — one measurement entry per feature with unit, status and detail.
- Automatic UTM zone selection from the dataset centroid; projected-source reuse when it is metric and sensible.
- Honest measurement statuses: `COMPLETED`, `NOT_REQUIRED` (points), `UNSUPPORTED` (GeometryCollection), `CRS_MISSING`, `NULL_GEOMETRY`, `ERROR`.
- Structured error envelope `{"error": {"code": ..., "message": ...}}` — no stack traces ever leave the process.
- ZIP hardening: Zip Slip, absolute/drive paths, symlinks, encrypted entries, entry-count, compression-ratio and total-expansion limits, conflicting entries.
- SQLite persistence (`data/geo_measure.db`), isolated storage per upload (`uploads/<id>/source<ext>`).
- Request logging middleware, service-level logs, configurable log level.
- 137 pytest tests covering validation, security, CRS logic, measurements and the HTTP surface.

## Architecture

```
                       ┌─────────────────────────────────────────────┐
                       │                 FastAPI app                │
                       │  main.py: lifespan, middleware, handlers   │
                       └───────────────┬─────────────────────────────┘
                                       │
        ┌──────────────────────────────┼──────────────────────────────┐
        │                              │                              │
  routes/health.py              routes/files.py                exception handlers
  GET /health                   POST /api/files/               AppException
                                GET /api/files/{id}/           RequestValidationError
                                GET /api/files/{id}/measurements/  HTTPException
                                       │                        Exception (500)
                                       ▼
                        ┌──────────────────────────────┐
                        │       services/file_service  │  upload → store → process
                        └──────┬───────────┬───────────┘
                               │           │
              ┌────────────────┘           └────────────────┐
              ▼                                             ▼
   services/zip_service                        services/geospatial_service
   safe extraction of .shp bundles             pyogrio (fallback: fiona)
   limits, traversal, symlinks                 KML / Shapefile → features
              │                                             │
              └────────────────┬────────────────────────────┘
                               ▼
                    services/crs_service
                    parse CRS → plan (AUTO_UTM / SOURCE_PROJECTED / UNAVAILABLE)
                    pyproj Transformer
                               │
                               ▼
                  services/measurement_service
                  shapely area (m²) / length (m) per feature
                               │
                               ▼
                    db/repository + SQLite ──► GET endpoints (JSON)
```

**Request flow for an upload:** validate → stream to disk → insert `PROCESSING`
record → parse → CRS plan → transform → measure → update record to `COMPLETED`
(or `FAILED` with a clean error message) → return `201`.

## Project Structure

```
geo-measure-api/
├── app/
│   ├── main.py                  # app factory, lifespan, request logging
│   ├── api/
│   │   └── routes/
│   │       ├── health.py        # GET /health
│   │       └── files.py         # upload / info / measurements routes
│   ├── core/
│   │   ├── config.py            # pydantic-settings, limits, paths
│   │   ├── exceptions.py        # AppException + global handlers
│   │   └── logging.py           # log formatting/level
│   ├── db/
│   │   ├── database.py          # SQLite schema + connection helper
│   │   └── repository.py        # record CRUD, FileRecord dataclass
│   ├── models/
│   │   └── schemas.py           # Pydantic responses and enums
│   ├── services/
│   │   ├── file_service.py      # upload lifecycle + processing pipeline
│   │   ├── zip_service.py       # hardened archive extraction
│   │   ├── geospatial_service.py# readers, feature extraction, CRS labels
│   │   ├── crs_service.py       # CRS classification, UTM choice, transform
│   │   └── measurement_service.py # area/length computation
│   └── utils/
│       ├── file_utils.py        # filename sanitising, magic bytes, paths
│       ├── geometry_utils.py    # geometry type helpers
│       └── serialization.py     # JSON-safe geometry/property conversion
├── tests/
│   ├── conftest.py              # isolated settings, clients, zip factories
│   ├── test_health.py           # test_upload.py      test_zip_security.py
│   ├── test_features.py         # test_geospatial.py  test_processing.py
│   ├── test_crs.py              # test_measurements.py
│   ├── test_file_info.py        # test_measurements_endpoint.py
│   ├── test_errors.py           # fixtures/ (sample.kml, mixed_geometry.kml)
├── sample_data/                 # files for manual/curl testing
├── uploads/                     # runtime storage (gitignored)
├── data/                        # SQLite database (gitignored)
├── requirements.txt  .env.example  pytest.ini  run.py
└── README.md
```

## Setup and Installation

Requirements: **Python 3.11+** (3.10+ should work), pip.

```bash
git clone https://github.com/devarasasank31/geo-measure-api.git
cd geo-measure-api

python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

Optional configuration — copy the example and edit values (all optional,
defaults are shown):

```bash
cp .env.example .env      # Windows: copy .env.example .env
```

| Variable | Default | Purpose |
| --- | --- | --- |
| `LOG_LEVEL` | `INFO` | Logging verbosity |
| `DEBUG` | `false` | Enables uvicorn reload in `run.py` |
| `UPLOAD_DIR` | `uploads` | Where uploads are stored |
| `DB_PATH` | `data/geo_measure.db` | SQLite database file |
| `MAX_UPLOAD_MB` | `50` | Per-file upload limit (413 beyond it) |
| `MAX_EXTRACT_MB` | `256` | Total extracted size budget |
| `MAX_ZIP_ENTRIES` | `1000` | Archive entry-count limit |
| `MAX_COMPRESSION_RATIO` | `500` | Zip-bomb ratio guard |
| `MEASUREMENT_DECIMALS` | `2` | Decimals in reported measurements |

## Running the Application

```bash
uvicorn app.main:app --reload
# or
python run.py
```

The server listens on `http://127.0.0.1:8000`. Storage directory and database
are created automatically at startup.

```bash
curl http://127.0.0.1:8000/health
# {"status":"ok"}
```

## API Reference

| Method | Path | Success | Purpose |
| --- | --- | --- | --- |
| `GET` | `/health` | `200` | Liveness probe |
| `POST` | `/api/files/` | `201` | Upload and process a `.kml` / `.zip` |
| `GET` | `/api/files/{id}/` | `200` | File metadata + extracted features |
| `GET` | `/api/files/{id}/measurements/` | `200` | Per-feature measurements |

### Upload a file

```bash
curl -F "file=@sample_data/sample.kml" http://127.0.0.1:8000/api/files/
curl -F "file=@sample_data/sample_shapefile.zip" http://127.0.0.1:8000/api/files/
```

```json
{
  "id": "8b5d203d08884f57bb63b2f4dc656656",
  "filename": "sample.kml",
  "feature_count": 3,
  "crs": "EPSG:4326",
  "status": "COMPLETED"
}
```

`status` can be `PROCESSING`, `COMPLETED` or `FAILED`. A `FAILED` record keeps
its `id` and exposes the clean reason through `GET /api/files/{id}/`.

### Read file information

```bash
curl http://127.0.0.1:8000/api/files/<id>/
```

```json
{
  "id": "8b5d203d08884f57bb63b2f4dc656656",
  "filename": "sample.kml",
  "feature_count": 3,
  "crs": "EPSG:4326",
  "status": "COMPLETED",
  "format": "kml",
  "size_bytes": 1030,
  "measurement_crs": "EPSG:32644",
  "measurement_strategy": "AUTO_UTM",
  "created_at": "2026-10-07T16:40:16Z",
  "error": null,
  "features": [
    {
      "feature_id": 0,
      "geometry_type": "Polygon",
      "geometry": {"type": "Polygon", "coordinates": [[[78.4, 17.3, 0.0], [78.401, 17.3, 0.0], ...]]},
      "crs": "EPSG:4326",
      "properties": {
        "Name": "North Plot",
        "description": "A rectangular parcel",
        "parcel_id": "P-001",
        "zone": "residential",
        "extrude": 0, "tessellate": 1, "visibility": 1
      }
    }
  ]
}
```

### Read measurements

```bash
curl http://127.0.0.1:8000/api/files/<id>/measurements/
```

```json
{
  "file_id": "8b5d203d08884f57bb63b2f4dc656656",
  "source_crs": "EPSG:4326",
  "measurement_crs": "EPSG:32644",
  "measurement_strategy": "AUTO_UTM",
  "measurements": [
    {"feature_id": 0, "geometry_type": "Polygon",  "measurement": 11778.93, "measurement_unit": "m²", "status": "COMPLETED", "detail": null},
    {"feature_id": 1, "geometry_type": "LineString", "measurement": 273.47, "measurement_unit": "m",  "status": "COMPLETED", "detail": null},
    {"feature_id": 2, "geometry_type": "Point",    "measurement": null, "measurement_unit": null, "status": "NOT_REQUIRED", "detail": "Points have no measurable area or length."}
  ]
}
```

Measurement statuses:

| Status | Meaning |
| --- | --- |
| `COMPLETED` | Area (m²) or length (m) computed after transformation |
| `NOT_REQUIRED` | Point features — nothing meaningful to measure |
| `UNSUPPORTED` | Geometry type that is not area/length measurable (e.g. GeometryCollection) |
| `CRS_MISSING` | No CRS information — measuring degrees would be wrong, so nothing is reported |
| `NULL_GEOMETRY` | Feature has no geometry |
| `ERROR` | Transformation/measurement failed for that feature |

## Interactive Documentation

- **Swagger UI:** <http://127.0.0.1:8000/docs> — try requests directly with the
  "Try it out" button; upload `sample_data/sample.kml`, copy the returned `id`
  into the read endpoints.
- **ReDoc:** <http://127.0.0.1:8000/redoc>
- **OpenAPI schema:** <http://127.0.0.1:8000/openapi.json>

Every route declares its success model, responses and short description, so
the generated docs match real behaviour.

## CRS Strategy

Measurements are only meaningful in a projected CRS whose units are metres.
The API resolves this explicitly (never implicitly):

| `measurement_strategy` | When it applies | Behaviour |
| --- | --- | --- |
| `SOURCE_PROJECTED` | Source CRS is already projected, in metres, not Web Mercator, and the data falls inside the CRS area of use | Reuse the source CRS — the file's own projection is the most faithful choice |
| `AUTO_UTM` | Source is geographic (degrees), or a projected CRS we refuse to measure in | Compute the dataset centroid → UTM zone `floor((lon+180)/6)+1` → EPSG `326xx` (north) / `327xx` (south); geometry transformed with `pyproj` |
| `UNAVAILABLE` | No CRS at all | `CRS_MISSING` per feature — the API does **not** assume EPSG:4326 |

**Why not EPSG:3857 (Web Mercator)?**

- It is a *display/tile* projection, not a measurement projection: linear scale
  grows with latitude, so area error reaches tens of percent (roughly 1.6×
  inflation at 45°, worse near the poles) and 3857 is undefined beyond ±85.06°.
- UTM keeps scale error below ~0.1 % within a zone, which is why the API picks
  the zone covering the data instead of the globally uniform but distorted 3857.
- If a file already carries a proper metric projection, reusing it avoids an
  unnecessary datum/zone hop.

Rounding: values are rounded to `MEASUREMENT_DECIMALS` (default 2) only for
presentation; computation happens in full float precision.

## Error Handling

All errors share one envelope — clients never see a stack trace, a traceback,
or a framework HTML page:

```json
{"error": {"code": "UNSUPPORTED_FILE_TYPE", "message": "Only KML files and ZIP archives containing Shapefiles are supported."}}
```

| Code | HTTP | Trigger |
| --- | --- | --- |
| `UNSUPPORTED_FILE_TYPE` | 400 | Extension is not `.kml`/`.zip` |
| `EMPTY_FILE` | 400 | Zero-byte upload |
| `INVALID_FILE_CONTENT` | 400 | Magic bytes do not match the extension |
| `CORRUPT_ARCHIVE` | 400 | Not a valid ZIP, or damaged member/CRC |
| `ARCHIVE_LIMIT_EXCEEDED` | 400 | Too many entries, extreme ratio, or too much output |
| `UNSAFE_ARCHIVE` | 400 | Traversal, absolute path, symlink, encryption, conflicting entries |
| `NO_SHAPEFILE_IN_ARCHIVE` | 400 | ZIP contains no `.shp` |
| `FILE_TOO_LARGE` | 413 | Upload exceeds `MAX_UPLOAD_MB` |
| `MALFORMED_INPUT` | 422 | Unreadable/invalid geospatial content |
| `PROCESSING_FAILED` | 422 | Unexpected failure while processing (details logged server-side) |
| `CRS_TRANSFORM_FAILED` | 422 | Transformation could not be built/applied |
| `VALIDATION_ERROR` | 422 | Request validation (missing multipart field, bad parameters) |
| `FILE_NOT_FOUND` | 404 | Unknown file id |
| `NOT_FOUND` / `METHOD_NOT_ALLOWED` | 404/405 | Unknown route / wrong verb |
| `INTERNAL_ERROR` | 500 | Unexpected exception (logged with traceback, generic message to clients) |

Rejected uploads are removed from disk; processing failures persist a `FAILED`
record with a clean `error_message` so the id still resolves. Unknown ids and
routes return `404` in the same envelope.

## Security

- **Content validation** by magic bytes (ZIP `PK..`, XML `<`) regardless of the
  client-declared `Content-Type`.
- **Zip Slip / traversal / drive-letter / absolute-path / null-byte** member
  names rejected *before* anything is written; destination re-checked against
  the extraction root.
- **Symlink entries and encrypted entries** rejected; entry count, compression
  ratio and total extracted bytes are bounded; damaged members surface as
  `CORRUPT_ARCHIVE`, conflicting entries as `UNSAFE_ARCHIVE`.
- **Storage paths are built only from a server-generated UUID + validated
  extension** — client filenames are sanitised for display only, never for paths.
- **Failed validation deletes the stored file**; extraction directories are
  cleaned up on every failure path.
- **No stack traces or internal messages** in responses; exceptions are logged
  server-side with `logger.exception`.

## Testing

```bash
python -m pytest          # 137 tests, -q via pytest.ini
```

| File | Covers |
| --- | --- |
| `test_health.py` | Health endpoint and app wiring |
| `test_upload.py` | Happy path, size limits, extensions, empty files, content mismatch |
| `test_zip_security.py` | Zip Slip, absolute/drive paths, symlinks, bombs, conflicting entries, hostile filenames |
| `test_features.py` | Feature schema, JSON-safety of geometry/properties |
| `test_geospatial.py` | KML/Shapefile parsing, engine fallback, multi-geometry KML |
| `test_processing.py` | Record lifecycle: `PROCESSING → COMPLETED/FAILED`, cleanup, persistence |
| `test_crs.py` | CRS detection, labels, UTM zone maths, projected reuse rules |
| `test_measurements.py` | Area/length values, statuses, missing CRS, rounding |
| `test_file_info.py` | Info endpoint, metadata, 404s, schema validation |
| `test_measurements_endpoint.py` | Measurements endpoint shape, units, statuses |
| `test_errors.py` | 500 handler, 405, validation context, request logging, no leaked internals |

Fixtures give every test an isolated `uploads/` directory and SQLite file, so
tests never touch real application data.

## Design Decisions

- **SQLite over PostgreSQL** — the spec needs a real persistence layer without
  external services; SQLite (stdlib `sqlite3`) keeps setup zero-friction while
  still exercising schema design and repository access patterns.
- **Synchronous endpoints + `run_in_threadpool`** — geospatial parsing and
  transformation are CPU/IO bound and release the GIL in C extensions; running
  them in Starlette's threadpool keeps the event loop responsive without a
  task queue.
- **Synchronous processing on upload** — returns a fully computed `201`
  response, matching the spec's simple contract; `PROCESSING` and `FAILED`
  statuses already exist so a background worker can replace
  `file_service.process_stored_file` later without API changes.
- **Persist the record before parsing** — uploads stay inspectable after
  failures, and ids are stable across the whole lifecycle.
- **Never assume a CRS** — inventing EPSG:4326 for a file without one would
  silently produce wrong metres; `CRS_MISSING` is the honest answer.
- **Two readers (pyogrio → fiona)** — engine choice varies by format/build;
  the fallback keeps KML and Shapefile support robust across environments.
- **Explicit error codes, not prose** — clients (and tests) branch on codes;
  messages are human-readable, codes are contract.
- **Configuration via `pydantic-settings`** — limits are tunable per
  environment and every limit has a test that shrinks it with `monkeypatch`.

## Learning

- **CRS literacy**: why degrees cannot be measured, why Web Mercator lies about
  area, how UTM zones are derived from longitude, and how `pyproj` expresses
  transformations (including datum shifts) in one line.
- **The geospatial stack**: GeoPandas/Shapely geometry algebra, the GDAL-backed
  readers (pyogrio vs fiona), Shapefile sidecars (`.shp/.shx/.dbf/.prj`), and
  KML's fixed lon/lat nature.
- **Defensive file handling**: magic bytes, archive traversal and zip-bomb
  defences, streaming writes with byte budgets, and cleaning up on every
  failure path.
- **API engineering**: structured error envelopes, Pydantic response contracts,
  OpenAPI annotations that generate useful docs, middleware logging, and test
  isolation for filesystem/database state.

## Future Scope

- Background processing (queue + `PROCESSING` polling) for large files.
- Additional inputs: GeoJSON, GeoPackage, DXF; additional outputs (CSV/GeoJSON export).
- PostGIS/PostgreSQL backend behind the same repository interface.
- Optional auth (API keys), rate limiting, per-user quotas.
- Geodesic (`pyproj.Geod`) area as a cross-check against projected area.
- Retention/cleanup jobs for old uploads and database records.
- Docker image + Compose, CI pipeline running the test suite.
- Per-request CRS override for users who need a specific measurement CRS.

## Limitations

- Single-process deployment: SQLite and in-request processing suit a demo/small
  load, not concurrent heavy uploads.
- No authentication, multi-tenancy or rate limiting.
- Memory/CPU scale with feature count — very large datasets would need chunking
  or a worker.
- KML parsing uses GDAL and, as a last-resort fallback, Python's XML parser;
  XML entity expansion risk is inherent to XML parsing of untrusted input.
- Shapefile `.prj` files with exotic/old WKT may be unreadable → reported as
  missing CRS rather than guessed.
- Projected measurements carry the small scale distortion of the chosen
  projection (mitigated by UTM, not eliminated).
- No upload retention policy yet: stored files accumulate until removed.

---

MIT License. Built with FastAPI, GeoPandas, Shapely, pyproj, pyogrio/fiona and
SQLite.
