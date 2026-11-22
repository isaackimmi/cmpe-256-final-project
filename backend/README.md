# TripWorld backend

To start both services, run `npm run dev` from the repository root. See the [root startup instructions](../README.md#run-locally).

To run just FastAPI, use Python 3.12 and run these commands from `backend/`:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m uvicorn --app-dir .. backend.main:app --reload
```

Open [the API docs](http://127.0.0.1:8000/docs) to try an endpoint, or [the health endpoint](http://127.0.0.1:8000/health) to check the service.

For dialog feedback, set `GEMINI_API_KEY` in the backend environment.
`GEMINI_MODEL` defaults to `gemini-3.5-flash-lite`. Browsing requires no key.
See the [feedback API contract and request diagrams](../docs/BACKEND_RECOMMENDATIONS_AND_AGENT.md).
