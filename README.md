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

Use Python 3.12 and Node.js 24. From the repository root, start the backend:

```sh
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload
```

In a second terminal, start the frontend from the repository root:

```sh
cd frontend
cp .env.example .env.local
npm ci
npm run dev
```

Open [the app](http://localhost:3000). Open [the connection check](http://localhost:3000/api/health) to verify that Next.js can reach FastAPI. A healthy response is `{"status":"ok"}`. A 503 means the backend URL is missing or the service could not answer successfully.

## Deploy

1. In Render, create a **Blueprint** from this repository. The root `render.yaml` configures the Python web service, build command, start command, and health check. After deployment, open `/health` on its Render URL.
2. In Vercel, import the same repository as a Next.js project. Set **Root Directory** to `frontend`, use Node.js 24, and keep the framework build defaults.
3. Set the Vercel environment variable `MODEL_API_URL` to the Render service's HTTPS origin. Set it in each environment that needs the backend, then deploy or redeploy.
4. Open `/api/health` on the Vercel URL and verify the same JSON response. This checks the full path from the website to the backend.

See the [Render Blueprint reference](https://render.com/docs/blueprint-spec) and [Vercel monorepo guide](https://vercel.com/docs/monorepos).
