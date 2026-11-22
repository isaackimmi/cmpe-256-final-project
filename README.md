# cmpe-256-final-project

## Dataset

[TripWorld by CRUISEResearchGroup on Hugging Face](https://huggingface.co/datasets/CRUISEResearchGroup/TripWorld)

## Project layout

| Directory | Purpose |
| --- | --- |
| `frontend/` | Next.js App Router website and server-side health check |
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

## Deploy

1. In Render, create a **Blueprint** from this repository. The root `render.yaml` configures the Python web service, build command, start command, and health check. After deployment, open `/health` on its Render URL.
2. In Vercel, import the same repository as a Next.js project. Set **Root Directory** to `frontend`, use Node.js 24, and keep the framework build defaults.
3. Set the Vercel environment variable `MODEL_API_URL` to the Render service's HTTPS origin. Set it in each environment that needs the backend, then deploy or redeploy.
4. Open `/api/health` on the Vercel URL and verify the same JSON response. This checks the full path from the website to the backend.

See the [Render Blueprint reference](https://render.com/docs/blueprint-spec) and [Vercel monorepo guide](https://vercel.com/docs/monorepos).

### Current API contract

The two catalog searches currently use labeled synthetic fixtures. Both accept
`q`, `limit` (default 20, maximum 100), and `offset` (default 0).

- `GET /places/search` searches past places across regions.
- `GET /destinations/search` searches destination names.

Both return `items` and `next_offset` (null on the last page). In the frontend,
TanStack Query's `useInfiniteQuery` can use the search type and debounced text
as the query key, start at offset zero, and pass each next offset as the page
parameter.

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
