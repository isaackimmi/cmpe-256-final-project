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

Use Python 3.12 and Node.js 24. From the repository root, start the backend:

```sh
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn --app-dir .. backend.main:app --reload
```

In a second terminal, start the frontend from the repository root:

```sh
cd frontend
cp .env.example .env.local
npm ci
npm run dev
```

Open [the app](http://localhost:3000). Open [the connection check](http://localhost:3000/api/health) to verify that Next.js can reach FastAPI. A healthy response is `{"status":"ok"}`. A 503 means the backend URL is missing or the service could not answer successfully.

### Try the local planner

Search past places for **Park** and select **Demo Park**. Choose **Kyoto (demo)**
as the destination and submit. The stub returns Demo Garden and Demo Market.
Pan or zoom to narrow the list to places in view. Panning outside Kyoto can
produce an empty list.

Set `NEXT_PUBLIC_MAPBOX_ACCESS_TOKEN` in `frontend/.env.local` to use the
Mapbox street and dark basemaps. Without a token the local map uses MapLibre
with bundled world land outlines. This preview supports pins, panning and zoom
without fetching street tiles. Both modes send viewport bounds to FastAPI.

## Deploy

1. In Render, create a **Blueprint** from this repository. The root `render.yaml` configures the Python web service, build command, start command, and health check. After deployment, open `/health` on its Render URL.
2. In Vercel, import the same repository as a Next.js project. Set **Root Directory** to `frontend`, use Node.js 24, and keep the framework build defaults.
3. Set the Vercel environment variable `MODEL_API_URL` to the Render service's HTTPS origin. Set `NEXT_PUBLIC_MAPBOX_ACCESS_TOKEN` to a public Mapbox token restricted to your site origins. Set these variables before building the frontend.
4. Open `/api/health` on the Vercel URL and verify the same JSON response. This checks the full path from the website to the backend.

See the [Render Blueprint reference](https://render.com/docs/blueprint-spec) and [Vercel monorepo guide](https://vercel.com/docs/monorepos).

### Current API contract

The two catalog searches currently use labeled synthetic fixtures. Both accept
`q`, `limit` (default 20, maximum 100), and `offset` (default 0).

- `GET /places/search` searches past places across regions.
- `GET /destinations/search` searches destination names.

Both return `items` and `next_offset` (null on the last page). In the frontend,
the search hooks use TanStack Query's `useInfiniteQuery` to request the first
page after typing settles and pass the returned offset for each subsequent page.

`POST /recommendations` accepts a destination, past places, and optional map
bounds. Example body:

```json
{"tripworld_region_id":"demo-kyoto","visited_place_ids":["demo-park"]}
```

The stub returns up to ten deterministic fixture results and model version
`stub-v1`. For viewport searches, add a `bounds` object with numeric `west`,
`south`, `east`, and `north` fields. Bounds narrow the selected destination.

`POST /feedback` is optional for this milestone and deferred. The recommendation
flow works without it.
