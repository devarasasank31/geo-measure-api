# Sample Data

Files for trying the API manually with Swagger UI, `curl` or any HTTP client.

| File | Format | CRS | Contents |
| --- | --- | --- | --- |
| `sample.kml` | KML | EPSG:4326 | Three features: a `Polygon`, a `LineString` and a `Point`, plus simple `ExtendedData` properties. |
| `sample_shapefile.zip` | Zipped Shapefile | EPSG:4326 | `parcels.shp` with its `.shx`, `.dbf`, `.prj` and `.cpg` sidecars: three polygon parcels with `parcel_id`, `area_ha` and `kind` attributes. |

Both files sit near Hyderabad, India, so UTM zone 44N (`EPSG:32644`) is selected
for measurement.

## Quick try

```bash
# KML
curl -F "file=@sample_data/sample.kml" http://127.0.0.1:8000/api/files/

# Zipped Shapefile
curl -F "file=@sample_data/sample_shapefile.zip" http://127.0.0.1:8000/api/files/
```

Each response contains an `id`; use it for the read endpoints:

```bash
curl http://127.0.0.1:8000/api/files/<id>/
curl http://127.0.0.1:8000/api/files/<id>/measurements/
```
