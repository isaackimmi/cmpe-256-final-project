# TripWorld destination-input catalog

Scope: city/destination autocomplete only. Past-visit POIs, recommendation candidates, Google-category filtering, and model coverage are deferred until the cleaned POI IDs are available.

- Pinned source revision: `254f142dfef42104783754019f7b7f4cfbf8d9a8`.
- Destinations: 1,165; exactly the source's distinct `r_o` set.
- Additional metro aliases: 344.
- Destinations with missing/raw-ID labels: 218 (retained).
- SQLite: 425,984 bytes.
- SHA-256: `1a0d8b6a857dcb774b6dd1fd4c37f9b82bb98d7976dedb687babf732e472324c`.
- Logical SHA-256: `c8f4b5eb2e41a7c9aebad5d8606b1d7cfb647cb2047ff5d3b306303ce08a2656`.
- Fresh-process checks: 27 passed.
- Rebuild logical match: True.

## Real search output

### Kyoto

```json
[
  {
    "region_id": "Q35765",
    "city_name": "Osaka",
    "country_name": "Japan",
    "canonical_metro_label": "Osaka (Keihanshin)",
    "label_missing": 0,
    "source_trip_count": 19726,
    "matched_name": "Kyoto",
    "matched_alias": "Kyoto"
  }
]
```

### Kyo

```json
[
  {
    "region_id": "Q35765",
    "city_name": "Osaka",
    "country_name": "Japan",
    "canonical_metro_label": "Osaka (Keihanshin)",
    "label_missing": 0,
    "source_trip_count": 19726,
    "matched_name": "Kyoto",
    "matched_alias": "Kyoto"
  }
]
```

### Accent-insensitive query

```json
{
  "query": "gulluk",
  "results": [
    {
      "region_id": "Q1004900",
      "city_name": "Güllük",
      "country_name": "Turkey",
      "canonical_metro_label": "Güllük",
      "label_missing": 0,
      "source_trip_count": 195,
      "matched_name": "Güllük",
      "matched_alias": null
    }
  ]
}
```

### Same-name destinations

```json
{
  "query": "guadalupe",
  "results": [
    {
      "region_id": "Q3778059",
      "city_name": "Guadalupe",
      "country_name": "Costa Rica",
      "canonical_metro_label": "Guadalupe",
      "label_missing": 0,
      "source_trip_count": 73,
      "matched_name": "Guadalupe",
      "matched_alias": null
    },
    {
      "region_id": "Q938835",
      "city_name": "Guadalupe",
      "country_name": "Mexico",
      "canonical_metro_label": "Guadalupe",
      "label_missing": 0,
      "source_trip_count": 152,
      "matched_name": "Guadalupe",
      "matched_alias": null
    }
  ]
}
```

### Least-active source destination

```json
{
  "region_id": "Q1807045",
  "city_name": "Careiro da Várzea",
  "normalized_name": "careiro da varzea",
  "country_name": "Brazil",
  "canonical_metro_label": "Careiro da Várzea",
  "label_missing": 0,
  "source_trip_count": 10
}
```

## Latency

```json
{
  "queries": 200,
  "median_ms": 0.15,
  "p95_ms": 0.271,
  "max_ms": 0.369,
  "query_cycle": [
    "Kyoto",
    "Kyo",
    "London",
    "Paris",
    "New York",
    "gulluk",
    "zzzzzzzzzzzznomatch"
  ],
  "conditions": "Warm SQLite/OS caches; seven warmup queries; one read-only connection; serial calls; excludes API/network time.",
  "python": "3.12.14",
  "sqlite": "3.53.1",
  "platform": "Linux-6.18.57-x86_64-with-glibc2.41"
}
```

Names retain their original scripts. Search uses published names and aliases; it does not invent translations, local-language equivalents, typo corrections, or arbitrary substring matches. FTS5 provides token prefixes; Japanese/Thai word segmentation is not claimed.

`source_trip_count` counts source travel records, not model-compatible POIs or available recommendations. A selectable destination does not guarantee that the future model can recommend venues there.

The notebook was executed locally with a Python kernel; Google-hosted Colab UI execution and deployment were not performed.

The upstream README hash differs from its upstream manifest; provenance is verified using the pinned Git blob. All three catalog source files must match the upstream SHA-256 manifest.

POI search and recommendation model integration are separate from this destination export.
