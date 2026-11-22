# TripWorld frontend

To start both services, run `npm run dev` from the repository root. See the [root startup instructions](../README.md#run-locally).

To run just Next.js, use Node.js 24 and run these commands from `frontend/`:

```sh
npm ci
cp -n .env.example .env.local
npm run dev
```

Open [localhost:3000](http://localhost:3000). Set `MODEL_API_URL` in `.env.local` to the origin of the FastAPI instance to use. The example points to port 8000 on your machine.
