// Only route handlers call this helper. API paths come from those handlers.
export async function forwardToBackend(request: Request, path: string) {
  const origin = process.env.MODEL_API_URL;
  if (!origin) {
    return Response.json(
      { error: "MODEL_API_URL is missing" },
      { status: 503 },
    );
  }

  try {
    const url = new URL(path, origin);
    url.search = new URL(request.url).search;
    const response = await fetch(url, {
      method: request.method,
      headers: { "Content-Type": "application/json" },
      body: request.method === "POST" ? await request.text() : undefined,
      cache: "no-store",
      signal: AbortSignal.any([request.signal, AbortSignal.timeout(10000)]),
    });
    return new Response(response.body, {
      status: response.status,
      headers: {
        "Content-Type":
          response.headers.get("Content-Type") ?? "application/json",
        "Cache-Control": "no-store",
      },
    });
  } catch {
    return Response.json({ error: "Backend unavailable" }, { status: 503 });
  }
}
