export async function GET() {
  const backend = process.env.MODEL_API_URL;
  if (!backend) {
    return Response.json({ error: "MODEL_API_URL is missing" }, { status: 503 });
  }

  try {
    const response = await fetch(new URL("/health", backend), {
      cache: "no-store",
      signal: AbortSignal.timeout(10000),
    });
    if (response.ok) {
      return Response.json(await response.json());
    }
  } catch {
    // Connection errors and timeouts report the same readiness status.
  }
  return Response.json({ error: "Backend unavailable" }, { status: 503 });
}
