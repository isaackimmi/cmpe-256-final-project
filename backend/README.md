# TripWorld backend

To start both services, run `npm run dev` from the repository root. See the [root startup instructions](../README.md#run-locally).

To run just FastAPI, use Python 3.12 and run these commands from `backend/`:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m uvicorn --app-dir .. backend.main:app --reload
```

Open [the API docs](http://127.0.0.1:8000/docs) to try an endpoint, or [the health endpoint](http://127.0.0.1:8000/health) to check the service.

## Destination catalog

`GET /destinations/search` reads the bundled, read-only
`artifacts/tripworld_destinations.sqlite`. It contains 1,165 real destination IDs
and 344 additional municipality aliases from TripWorld revision
`254f142dfef42104783754019f7b7f4cfbf8d9a8`. No POI cleaning or model outputs are
included in this database. The SQLite file and upstream README/provenance scripts
are tracked so Render's `rootDir: backend` deployment includes them automatically.
No new runtime packages or persistent disk are needed; Python's SQLite must
support FTS5. Startup validates the schema and FTS5 and fails with an actionable
error if the artifact is absent or incompatible. Set `TRIPWORLD_DESTINATIONS_DB`
to an alternative SQLite path when needed; the default is resolved relative to
the Python module, independent of the working directory.

The existing `q`, `limit` (default 20, maximum 100), `offset`, `items`, and
`next_offset` contract is retained. Blank queries browse all canonical regions.
Queries match safe token prefixes, aliases, country context, and accent-folded
Latin names; results are deduplicated before pagination. Published scripts are
preserved without a language/ASCII filter. Translations and Japanese/Thai word
segmentation are not added. Matching names rank exactly before prefixes, with
canonical matches before aliases. Example:

```json
{
  "items": [{
    "id": "Q35765",
    "name": "Kyoto",
    "country": "Japan",
    "canonical_name": "Osaka",
    "canonical_metro_label": "Osaka (Keihanshin)",
    "matched_alias": "Kyoto"
  }],
  "next_offset": null
}
```

`id` is always the real canonical TripWorld region ID. `name` preserves the alias
that matched, when present, so the picker can show Kyoto and its Osaka metro
scope. The frontend's initial sample and map references now use `Q35765` and
London's `Q84`. Past-place search still uses the existing sample POIs.
Recommendation validation uses SQLite IDs; sample results remain available for
Kyoto/Osaka and London and are marked `stub-v1` with sample explanations. Other
valid destinations return 503 (recommendations unavailable), rather than a
misleading empty model result or an unknown-destination 422. This does not connect
the trained model or assert recommendation coverage.

### Reproduce and verify

From the repository root with Python 3.12:

```sh
python3.12 -m venv .venv-catalog
.venv-catalog/bin/pip install -r scripts/requirements-catalog.txt
.venv-catalog/bin/python scripts/build_tripworld_catalog.py
.venv-catalog/bin/python scripts/verify_tripworld_catalog.py \
  --database backend/artifacts/tripworld_destinations.sqlite \
  --source-dir data/tripworld \
  --output reports/tripworld_catalog_validation.json
```

Or run [Notebook 4](../notebooks/04_destination_catalog.ipynb) in Colab or locally.
It reads only distinct destination IDs/trip counts from
`travel_behaviors.parquet`, labels from `region_labels.parquet`, and
`metro_mapping_clean.json`; it never reads POIs, Google categories, or reviews.
Downloads are cached under ignored `data/tripworld/`. The builder verifies source
SHA-256 hashes and preserves the upstream redistribution files. Those provenance
files are checked against pinned Git blobs because the upstream README checksum
is stale. SQLite is built at a temporary path, validated in a fresh Python
process, and only then replaces the final artifact. The notebook rebuilds twice
and requires identical logical records and counts. Build evidence is under
`reports/tripworld_catalog_*`; temporary SQLite files and ZIP downloads are
ignored, while the small final artifact is deliberately versioned.

Backend integration tests, from the repository root:

```sh
backend/.venv/bin/pip install -r backend/requirements-test.txt -r scripts/requirements-catalog.txt
backend/.venv/bin/python -m unittest discover -s tests -p 'test_destination*.py' -v
backend/.venv/bin/python -m unittest discover -s tests -p test_backend_contract.py -v
```

The catalog unit tests also need the catalog-build requirements in the same test
environment. The serving backend needs only `backend/requirements.txt`.

### Source-data limitation

Coverage and names reflect the pinned source, not a list of every world city.
For example, Maui is not a destination label/alias in this release, although the
past-place fixtures still include Maui visits. Alias consistency checks establish
agreement with the published mapping, not geographical correctness. An upstream
oddity is retained explicitly: municipality `Q187153` is labeled
`14th arrondissement of Paris` but maps to Osaka (`Q35765`). Consequently a Paris
query can match that published alias. This needs source-data review; it is not
silently corrected by fabricating IDs or translations in the API.

TripWorld is for non-commercial research. Preserve its upstream README and
provenance scripts when redistributing the database.
