# cmpe-256-final-project

## Dataset

[TripWorld by CRUISEResearchGroup on Hugging Face](https://huggingface.co/datasets/CRUISEResearchGroup/TripWorld)

## Project layout

| Directory | Purpose |
| --- | --- |
| `frontend/` | Next.js map planner and server-side API routes |
| `backend/` | FastAPI service deployed on Render |
| `backend/artifacts/` | Place for future model exports and matching serving files |
| `notebooks/` | [Starter KDD notebook](notebooks/tripworld_kdd.ipynb) for Google Colab |
| `reports/` | Project report, figures, and experiment results |

## Run locally

From the repository root on macOS or Linux, with Python 3.12, Node.js 24 and npm installed, run:

```sh
npm run dev
```

This installs the dependencies on first use, starts FastAPI and Next.js with reload, and connects them. Press Ctrl+C to stop both. The launcher checks the dependency files on subsequent runs. Use `PORT` to change the web port or `BACKEND_PORT` to change the API port.

Open [the app](http://localhost:3000) or [the frontend-to-backend health check](http://localhost:3000/api/health). A healthy response is `{"status":"ok"}`.

For a single service, see the [frontend instructions](frontend/README.md) or [backend instructions](backend/README.md).

### Try the local planner

The A1 planner opens with Kyoto and two sample Maui visits. Select **Find places**
to see four Kyoto recommendations. Choose a row or pin to highlight the corresponding place.
Pan or zoom to narrow the list to places in view. Panning outside Kyoto can
produce an empty list.

Set `NEXT_PUBLIC_MAPBOX_ACCESS_TOKEN` in `frontend/.env.local` to use the
Mapbox street and dark basemaps. Without a token the local map uses MapLibre
with the supplied day/night street maps for Kyoto and London and a world outline
elsewhere. This preview supports pins, panning and zoom without a tile service. Both modes send viewport bounds to FastAPI.

## Deploy

1. In Render, create a **Blueprint** from this repository. The root `render.yaml` configures the Python web service, build command, start command, and health check. After deployment, open `/health` on its Render URL.
2. In Vercel, import the same repository as a Next.js project. Set **Root Directory** to `frontend`, use Node.js 24, and keep the framework build defaults.
3. Set the Vercel environment variable `MODEL_API_URL` to the Render service's HTTPS origin. Set `NEXT_PUBLIC_MAPBOX_ACCESS_TOKEN` to a public Mapbox token restricted to your site origins. Set these variables before building the frontend.
4. Open `/api/health` on the Vercel URL and verify the same JSON response. This checks the full path from the website to the backend.

See the [Render Blueprint reference](https://render.com/docs/blueprint-spec) and [Vercel monorepo guide](https://vercel.com/docs/monorepos).

### Current API contract

Destination search uses the bundled SQLite catalog of 1,165 TripWorld regions. Past-place search still uses sample fixtures. An empty query lists the catalog. Both accept
`q`, `limit` (default 20, maximum 100), and `offset` (default 0).

- `GET /places/search` searches past places across regions.
- `GET /destinations/search` searches real destination names, metro aliases, and country context.

Both return `items` and `next_offset` (null on the last page). In the frontend,
the search hooks use TanStack Query's `useInfiniteQuery` to request the first
page after typing settles and pass the returned offset for each subsequent page.

`POST /recommendations` accepts a destination, past places, and optional map
bounds. Example body:

```json
{"tripworld_region_id":"Q35765","visited_place_ids":["a1-mamas","a1-golf"]}
```

Kyoto searches return `Q35765`, the canonical Osaka (Keihanshin) region, with
`name: "Kyoto"`, `canonical_name: "Osaka"`, and the matched alias/metro label.
The picker shows that broader recommendation area. Canonical and alias searches
return the same real region ID.

Recommendations remain a sample service: Kyoto/Osaka (`Q35765`) and London
(`Q84`) return up to ten deterministic fixtures with model version `stub-v1`.
Other valid destinations return 503 with an availability message until model
integration is ready; unknown destination IDs return 422. No real model inference
is introduced by the destination-catalog integration. For viewport searches, add a `bounds` object with numeric `west`,
`south`, `east`, and `north` fields. Bounds narrow the selected destination.

`POST /feedback` is optional for this milestone and deferred.

### Frontend file naming

Use PascalCase for React component files (`MapView.tsx`) and camelCase for
hook files (`useSearch.ts`). Next.js route entry files follow its prescribed
names, including `page.tsx`, `layout.tsx`, and `route.ts`.

### Destination catalog export

The validated destination-only database is tracked at
`backend/artifacts/tripworld_destinations.sqlite` (416 KiB), with upstream
redistribution provenance in `backend/artifacts/tripworld_provenance/`. Render's
normal Git deployment includes these files; no persistent disk, raw-data download,
or catalog build is required at service startup. Startup fails clearly when the
artifact is missing, incompatible, or SQLite FTS5 is unavailable.

[Notebook 4](notebooks/04_destination_catalog.ipynb) builds the catalog from three
pinned TripWorld sources, checks all destination IDs and published aliases, and
repeats the build to verify logical reproducibility. It is separate from the ML
preprocessing notebooks. See [backend catalog instructions](backend/README.md#destination-catalog)
for reproduction, response fields, tests, and source-data limitations.
