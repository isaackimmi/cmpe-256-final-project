---
pretty_name: Trip World
license: cc-by-nc-4.0
license_name: trip-world-noncommercial
license_link: LICENSE
language:
- en
- ja
- tr
- ms
- pt
- th
- es
- multilingual
multilinguality:
- multilingual
size_categories:
- 100M<n<1B
task_categories:
- text-classification
- text-retrieval
- summarization
- other
task_ids:
- sentiment-classification
- multi-class-classification
tags:
- POI
- trajectory-recommendation
- next-location-prediction
- check-ins
- mobility
- tourism
- cross-city
- foursquare
- google-maps
- reviews
annotations_creators:
- machine-generated
- found
language_creators:
- found
source_datasets:
- extended
configs:
- config_name: travel_behaviors
  data_files: travel_behaviors.parquet
- config_name: pois
  data_files: pois.parquet
- config_name: regions
  data_files: region_labels.parquet
- config_name: metadata
  data_files: metadata/metadata_all.parquet
- config_name: place_attributes
  data_files: metadata/place_attributes.parquet
- config_name: reviews
  data_files: reviews/reviews_all.parquet
---

# Trip World

**Trip World** is a publicly redistributable, METRO-level cross-city travel
benchmark.  It pairs a large corpus of out-of-town travel sequences with
rich Foursquare and Google Maps point-of-interest (POI) metadata and an
unified Google reviews corpus.  The dataset is designed to support:

- **Trajectory recommendation** — recommend a sequence of POIs in an
  unfamiliar city, given the traveller's home-city behaviour and a
  desired start / end / length.
- **Cross-city POI ranking and next-POI prediction** — score POIs in a
  destination region by likelihood for an out-of-town visitor.
- **Place modelling** — text/category/sentiment work driven by 186 M
  Google reviews and structured FSQ + Google attributes for 687 K POIs.
- **Tourism and mobility analytics** — aggregate analyses of travel
  flows between 1,173 cities in 90+ countries.

The release is built on top of the STD-2018 check-in stream, with metro-
consolidation, hometown discovery, traveller filtering, and POI
enrichment applied; see *Provenance* below for the exact pipeline.


## Headline statistics

| Quantity                                       | Value          |
|------------------------------------------------|---------------:|
| Travel-behavior records (τ)                    | **518,567**    |
| Distinct travellers                            | **148,402**    |
| Hometown regions / destination regions         | 723 / 1,165    |
| Distinct (hometown → destination) pairs        | 6,246          |
| Qualifying check-ins                           | 7,416,219      |
| Distinct trails (sessions)                     | 2,723,551      |
| Distinct POIs                                  | 687,173        |
| POIs with Google metadata                      | **566,798 (82.5%)** |
| POIs with ≥ 1 review                           | **524,530 (76.3%)** |
| POIs with ≥ 1 *text* review                    | 516,689 (75.2%) |
| Total reviews                                  | **186,760,186** |
| Reviews with non-empty text                    | 135,355,243 (72.5%) |
| POIs with extra place attributes (desc / hours / price) | 28,776 |
| Distinct cities (Wikidata QIDs)                | 1,173          |
| Time span                                      | 2017-10-03 — 2018-10-20 |

Geographic coverage is strongest in East Asia and the Mediterranean
(Japan, Turkey, Malaysia, USA, Brazil, Thailand, Mexico, Philippines …).
See the figures bundled with the source repository for breakdowns.


## Definitions

A **travel-behavior record** captures one traveller's activity around
one out-of-town destination.  Following the dataset's formal definition,
each τ record is a five-tuple

> τ = (u, c_h, c_o, r_h, r_o)

with the following components:

| Symbol | Meaning                                                       |
|--------|---------------------------------------------------------------|
| `u`    | the traveller (anonymous integer ID, 1..148,402)              |
| `r_h`  | their identified hometown region (Wikidata city QID)          |
| `r_o`  | the out-of-town destination region (Wikidata city QID)        |
| `c_h`  | the traveller's check-in stream **at home** around this trip  |
| `c_o`  | the traveller's check-in stream **at the destination**        |

`c_h` and `c_o` are sequences of `(trail_id, venue_id, venue_category,
venue_schema, ts)` records.  Each `trail_id` identifies a single
contiguous session of check-ins (one "trajectory" in the trajectory-
recommendation sense); a single τ record may contain several distinct
trails on each side because the same traveller can have multiple home
sessions and multiple visits to the same destination.

A **POI** is identified by a Foursquare place ID
(`foursquare:<24-hex>`).  Each POI is annotated with a Wikidata-QID
locality (the city it belongs to), a Foursquare venue category, a
schema.org venue type, and (for ~82 % of POIs) the corresponding Google
Maps CID and rich Google metadata.


## Layout

```
trip_world/
├── README.md                          (this file)
├── MANIFEST.json                      — file list with sizes, sha256, and row counts
├── metro_mapping_clean.json           — metro consolidation map (municipality QID → parent metro QID)
├── travel_behaviors.parquet           — 518,567 τ records
├── pois.parquet                       — 687,173 POI summaries (per-POI usage stats + flat google_*)
├── region_labels.parquet              — 1,173 (region_id → city name + country)
├── metadata/
│   ├── metadata_all.parquet           — 687,173 rows; full Foursquare + Google metadata per POI
│   └── place_attributes.parquet       — 28,776 rows; description / hours / price for the most enriched POIs
├── reviews/
│   └── reviews_all.parquet            — 186,760,186 unified Google reviews
└── _scripts/                          — full build-pipeline source code (reproduces the dataset)
```


## Schema (column reference)

### `travel_behaviors.parquet`  (518,567 rows)

| Column        | Type                              | Notes |
|---------------|-----------------------------------|-------|
| `user_id`     | int64                             | 1..148,402, fresh public IDs (see *Privacy*) |
| `r_h`         | string                            | hometown region — Wikidata QID, e.g. `Q35178` |
| `r_o`         | string                            | destination region — Wikidata QID |
| `n_home_ci`   | int64                             | total home-side check-ins in `c_h` |
| `n_travel_ci` | int64                             | total destination-side check-ins in `c_o` |
| `c_h`         | list<struct>                      | home check-ins (see element schema below) |
| `c_o`         | list<struct>                      | destination check-ins (same element schema) |

Each element of `c_h` / `c_o` is:

| Field              | Type                       | Notes |
|--------------------|----------------------------|-------|
| `trail_id`         | int64                      | 1..2,723,551 (fresh public IDs) — same trail can re-appear across τ records |
| `venue_id`         | string                     | `foursquare:<24-hex>` POI key |
| `venue_category`   | string                     | Foursquare category UUID (4-byte hex, optional) |
| `venue_schema`     | string                     | schema.org venue type, e.g. `schema:CafeOrCoffeeShop` |
| `ts`               | timestamp[us, UTC]         | observation time |

### `pois.parquet`  (687,173 rows)

POI-level summary, optimised for the 99 % of analyses that only need
the flat columns.  Every POI in the benchmark appears exactly once.

| Column                | Type                | Notes |
|-----------------------|---------------------|-------|
| `fsq_place_id`        | string              | primary key |
| `locality`            | string              | Wikidata QID of the city |
| `venue_category`      | string              | Foursquare category UUID |
| `venue_schema`        | string              | schema.org type |
| `n_checkins`          | int64               | total check-ins for this POI in the dataset |
| `n_users_visited`     | int64               | distinct travellers who visited |
| `google_cid`          | string \| null      | Google Maps customer ID (= `place_id` in some APIs) |
| `google_name`         | string \| null      | Google business name |
| `google_full_address` | string \| null      | Google formatted address |
| `google_address`      | string \| null      | Google street address |
| `google_website`      | string \| null      | Google business website |
| `google_rating`       | double \| null      | average Google star rating |
| `google_num_reviews`  | int64 \| null       | Google review count |
| `google_categories`   | list<string> \| null| Google category labels |
| `google_place_id`     | string \| null      | Google Places API ID (when known) |
| `google_gmaps_url`    | string \| null      | canonical maps.google.com URL |
| `google_meta_source`  | string              | provenance tag identifying which collection step produced this metadata |
| `has_google_metadata` | bool                | convenience flag |
| `n_reviews`           | int64               | reviews available for this POI |
| `n_reviews_with_text` | int64               | reviews with non-empty text |
| `review_source`       | string              | provenance tag |
| `has_reviews`         | bool                | convenience flag |

### `metadata/metadata_all.parquet`  (687,173 rows)

Per-POI Foursquare + Google metadata.  Same `fsq_place_id` primary key
as `pois.parquet`; richer FSQ fields (name, lat/lon, address, country,
website, …).  Personal-leaning Foursquare contact fields
(`fsq_email`, `fsq_tel`, `fsq_facebook_id`, `fsq_instagram`,
`fsq_twitter`) are intentionally **not** present.

Notable columns: `fsq_name`, `fsq_latitude`, `fsq_longitude`,
`fsq_address`, `fsq_locality`, `fsq_region`, `fsq_country`,
`fsq_postcode`, `fsq_formatted_address`, `fsq_category_ids`,
`fsq_category_labels`, `fsq_website`, `fsq_date_created`,
`fsq_date_refreshed`, `fsq_date_closed`.

The `google_*` columns mirror those in `pois.parquet`.

### `metadata/place_attributes.parquet`  (28,776 rows)

Rich place-level attributes for the most enriched POIs (descriptions,
opening hours, price tier, free-form attributes).

| Column              | Type   | Notes |
|---------------------|--------|-------|
| `fsq_place_id`      | string | join key |
| `google_cid`        | string | the Google CID this enrichment came from |
| `search_query`      | string | query used to recover the place |
| `match_dist_m`      | double | metres between FSQ point and Google point |
| `match_name_sim`    | double | normalized name-similarity score |
| `description_short` | string | one-line description |
| `description_long`  | string | longer description |
| `hours_today`       | string | today's opening hours, free-text |
| `hours_week`        | string | weekly hours, free-text |
| `price_token`       | string | Google price symbol (`$`, `$$`, …) |
| `price_min`         | string | min price (when known) |
| `price_max`         | string | max price (when known) |
| `attributes`        | string | JSON-encoded attribute bag |
| `n_inline_reviews`  | int64  | count of reviews scraped at enrichment time |
| `fetched_at`        | string | timestamp of enrichment fetch |

### `region_labels.parquet`  (1,173 rows)

| Column         | Type   | Example      |
|----------------|--------|--------------|
| `region_id`    | string | `Q100`       |
| `city_name`    | string | `Boston`     |
| `country_qid`  | string | `wd:Q30`     |
| `country_name` | string | `United States` |

### `reviews/reviews_all.parquet`  (186,760,186 rows)

Unified Google reviews corpus, one row per review.

| Column           | Type                  | Notes |
|------------------|-----------------------|-------|
| `fsq_place_id`   | string                | links to `pois.parquet` |
| `google_cid`     | string                | links to `metadata_all.parquet` |
| `review_id`      | string                | Google's review ID |
| `rating`         | int64                 | 1..5 |
| `text`           | string                | original review text (may be empty) |
| `text_translated`| string \| null        | Google's machine translation, if any |
| `lang`           | string \| null        | BCP-47 language tag |
| `relative_time`  | string \| null        | Google's "3 weeks ago" string |
| `timestamp_us`   | int64                 | absolute review time, microseconds since epoch |
| `review_time`    | timestamp[us, UTC]    | same value, parsed |
| `owner_reply`    | string \| null        | business-owner reply text, if any |
| `source`         | string                | provenance tag identifying which collection step produced this review |
| `author_pid`     | string                | salted blake2b 16-hex pseudonym (see *Privacy*) |

The display name and Google profile ID of each reviewer are **removed
from the public release**; the `author_pid` column lets you link
multiple reviews from the same author *within* the dataset without
exposing real identities.

### `metro_mapping_clean.json`

A JSON dictionary mapping individual municipality QIDs to the parent
metro QID used as `region_id` everywhere else.  Useful if you want to
recover the original sub-municipal granularity, or extend the mapping.


## Quick start

The release uses Apache Parquet throughout; any tool that reads parquet
will work.  Below are minimal examples in three common stacks.

### Python — pandas / pyarrow

```python
import pandas as pd, pyarrow.parquet as pq
ROOT = "/path/to/trip_world"

travel  = pq.read_table(f"{ROOT}/travel_behaviors.parquet").to_pandas()
pois    = pq.read_table(f"{ROOT}/pois.parquet").to_pandas()
regions = pq.read_table(f"{ROOT}/region_labels.parquet").to_pandas()

# How many trips originate from each city?
top_origins = (travel.merge(regions, left_on="r_h", right_on="region_id")
                     .groupby("city_name").size()
                     .sort_values(ascending=False).head(10))
print(top_origins)
```

### Python — DuckDB (recommended for the 23 GB review file)

DuckDB streams parquet without loading everything into RAM and supports
the full SQL surface, including joins across files.

```python
import duckdb
con = duckdb.connect()

con.execute(f"""
  CREATE VIEW travel  AS SELECT * FROM '{ROOT}/travel_behaviors.parquet';
  CREATE VIEW pois    AS SELECT * FROM '{ROOT}/pois.parquet';
  CREATE VIEW regions AS SELECT * FROM '{ROOT}/region_labels.parquet';
  CREATE VIEW reviews AS SELECT * FROM '{ROOT}/reviews/reviews_all.parquet';
""")

# Top destinations for travellers from Boston (Q100):
con.sql("""
  SELECT regions.city_name, COUNT(*) AS trips
  FROM travel JOIN regions ON travel.r_o = regions.region_id
  WHERE travel.r_h = 'Q100'
  GROUP BY regions.city_name
  ORDER BY trips DESC
  LIMIT 10
""").show()

# Average review rating per category in Tokyo:
con.sql("""
  SELECT pois.venue_schema,
         AVG(reviews.rating)        AS avg_rating,
         COUNT(*)                   AS n
  FROM reviews
  JOIN pois ON reviews.fsq_place_id = pois.fsq_place_id
  WHERE pois.locality = 'Q1490'   -- Tokyo
  GROUP BY pois.venue_schema
  HAVING COUNT(*) > 100
  ORDER BY avg_rating DESC
""").show()
```

### Iterating over the trajectories of one traveller

```python
import pyarrow.parquet as pq, pandas as pd
tb = pq.read_table(f"{ROOT}/travel_behaviors.parquet").to_pandas()

row = tb.iloc[0]
print(f"User {row['user_id']} travelled from {row['r_h']} to {row['r_o']}")
print(f"  {row['n_home_ci']} home check-ins, {row['n_travel_ci']} destination check-ins")

# Group destination check-ins by trail (= individual trajectory):
import collections
trails = collections.defaultdict(list)
for ck in row["c_o"]:
    trails[ck["trail_id"]].append(ck)

for trail_id, points in trails.items():
    points.sort(key=lambda p: p["ts"])
    venues = " → ".join(p["venue_schema"] for p in points)
    print(f"  trail {trail_id}: {venues}")
```

### Counting reviews per place without loading all 23 GB

```python
con.sql("""
  SELECT fsq_place_id, COUNT(*) AS n_reviews
  FROM '{ROOT}/reviews/reviews_all.parquet'
  GROUP BY fsq_place_id
  ORDER BY n_reviews DESC
  LIMIT 20
""".format(ROOT=ROOT)).show()
```


## Common join patterns

| To go from … | … to …                       | Join key                                   |
|--------------|------------------------------|--------------------------------------------|
| τ record     | hometown / destination name  | `travel.r_h = regions.region_id` (and `r_o`) |
| τ record     | per-POI usage / Google meta  | element `venue_id = pois.fsq_place_id`     |
| τ record     | full FSQ + Google metadata   | element `venue_id = metadata_all.fsq_place_id` |
| POI summary  | rich place attributes        | `pois.fsq_place_id = place_attributes.fsq_place_id` |
| POI summary  | reviews                      | `pois.fsq_place_id = reviews.fsq_place_id` |
| Reviews      | place-level Google ratings   | `reviews.google_cid = pois.google_cid`     |
| Reviews      | author identity (within set) | `reviews.author_pid` (no external linking) |
| Region       | municipalities folded into it| `metro_mapping_clean.json[municipality_qid] == region_id` |


## Privacy and redaction

The following transforms have been applied relative to the build-time
working set so the release can be redistributed without exposing
individual identities:

1. **User IDs.**  `user_id` in `travel_behaviors.parquet` is remapped
   to a fresh consecutive 1..148,402 sequence; original
   STD-2018-derived IDs are not present.

2. **Trail IDs.**  `trail_id` inside each `c_h` / `c_o` element is
   likewise remapped to a fresh consecutive 1..2,723,551 sequence.

3. **Reviewer identity.**  Reviewer display names (`author`) are
   removed entirely.  The original numeric Google `author_id` is
   replaced with a salted blake2b pseudonym `author_pid` (16 hex
   characters per author).  The salt is generated at release time and
   kept private; cross-review author linking remains possible *inside*
   the dataset but cannot be inverted to a real Google profile.

4. **Foursquare contact fields.**  The columns `fsq_email`, `fsq_tel`,
   `fsq_facebook_id`, `fsq_instagram`, `fsq_twitter` are dropped from
   `metadata_all.parquet`.

5. **Review text.**  Review bodies are kept verbatim (they are the
   dataset's primary signal).  Users of this release should be aware
   that user-generated text may incidentally contain personal
   references and should treat downstream analyses accordingly.

If you discover residual identifying information that we missed, please
contact the maintainers so it can be redacted in the next release.


## Reproducibility

The build-pipeline source is shipped under `_scripts/` for
documentation and audit purposes.  **Re-running it end-to-end requires
several external data sources that are not part of this release** — see
the table below.  The released parquet files are the canonical
artefacts; the scripts let you verify *how* they were produced and
re-derive subsets you may need.

### What the scripts can re-derive

| Stage(s) | Output | External data needed |
|----------|--------|----------------------|
| 0–6      | metro map, τ records, POIs, region labels | STD-2018 raw check-in CSV |
| 7        | per-POI Foursquare metadata    | Foursquare Open Source Places parquet dump |
| 10       | extra FSQ enrichment for new POIs | Foursquare Open Source Places parquet dump |
| 11       | FSQ-API rescue of unresolved POIs | Foursquare Places API key |
| 12–13    | UCSD-bridge Google metadata for new POIs | UCSD all20 + benchmark POI corpus |
| 14–16    | merged Google reviews + place attributes | **raw GCP scrape shards (not redistributable; the scrape code is not included)** |

In other words, the structural side of Trip World (τ records, POIs,
region labels, FSQ metadata) can be reproduced if you supply STD-2018
and an FSQ-OS dump.  The Google reviews corpus cannot be re-derived
from this release alone — it is provided as a static parquet because
the scrape that produced it is not redistributable.

### Configuring paths

All scripts read their filesystem locations from environment variables
so the source tree contains no personal paths.  Defaults assume the
script is launched from inside the release's `_scripts/` subfolder.

```bash
export TRIP_WORLD_ROOT=/path/to/trip_world           # default: ../ relative to the script
export STD_2018_PATH=/path/to/std_2018.csv           # raw STD-2018 stream
export FSQ_OS_PARQUET_GLOB="/path/to/fsq_os/places/parquet/*.parquet"
export PRECURSOR_BUILD_ROOT=/path/to/previous_build  # optional; an earlier output of this pipeline whose POI metadata and reviews stages 5/7/8/16 inherit from. Omit unless you are rebuilding incrementally on top of a prior run.
export GMAPS_FULL_ROOT=/path/to/gmaps_full_dataset   # optional, only for stage 12
export DUCKDB_TMP_DIR=/tmp/duckdb_trip_world          # any large local scratch directory
export FSQ_API_KEY=fsq3...                            # only if running stage 11
```

### Stage-by-stage map

```
_scripts/00_build_metro_map.py            — metro consolidation map (Wikidata SPARQL)
_scripts/01_consolidate_filter.py         — apply consolidation, filter to MIN_PAIR
_scripts/02_hometown_discovery.py         — temporal-decay hometown identification
_scripts/03_build_travelers.py            — split travellers / non-travellers
_scripts/04_build_travel_behaviors.py     — emit τ records
_scripts/05_build_pois.py                 — per-POI usage stats
_scripts/06_build_region_labels.py        — Wikidata-derived city names
_scripts/07_subset_metadata.py            — slice FSQ-OS metadata
_scripts/08_subset_reviews.py             — slice reviews
_scripts/09_validate.py                   — invariants + descriptive stats
_scripts/10_enrich_new_pois.py            — local-dump enrichment for new POIs
_scripts/11_fsq_api_recover.py            — live FSQ Places API recovery
_scripts/12_ucsd_bridge.py                — UCSD all20+bench match
_scripts/13_merge_ucsd_into_metadata.py   — merge UCSD matches into metadata
_scripts/14_merge_gcp_search_results.py   — merge Stage-1 GCP scrape shards (shards not shipped)
_scripts/15_merge_stage2_reviews.py       — merge Stage-2 listugcposts shards (shards not shipped)
_scripts/16_unify_reviews.py              — final review unification
_scripts/lib_wikidata.py                  — small Wikidata helper
_scripts/viz_clean_raw.py                 — descriptive figures
_scripts/viz_traj_length.py               — trajectory-length figure
```

No API keys are embedded in any released script; stages that hit
external services (Wikidata SPARQL, FSQ Places API) read credentials
from environment variables or CLI flags exclusively.


## Citation

If you use Trip World in academic work, please cite the accompanying
paper
```
@article{li2026empirical,
  title={An Empirical Evaluation of Cross-City POI Recommendation on a Large-Scale Benchmark},
  author={Li, Peibo and Song, Yang and Xue, Hao and de Rijke, Maarten and Salim, Flora D},
  journal={arXiv preprint arXiv:2608.27840},
  year={2026}
}
```


## License

The Trip World release is distributed for **non-commercial research
use** only.  Redistributions must preserve this README and the
provenance scripts in `_scripts/`.  Use of the dataset implies
acceptance of the upstream Foursquare Open Source Places licence and
the Google Maps Platform Terms of Service for any further analysis
that re-fetches data from those services.

Released on 2026-05-05.
