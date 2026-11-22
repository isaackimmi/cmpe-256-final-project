export async function fetchJson<T>(
  url: string,
  options: RequestInit,
): Promise<T> {
  const response = await fetch(url, options);
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const message = body?.error ?? body?.detail;
    throw new Error(
      typeof message === "string"
        ? message
        : `Request failed (${response.status})`,
    );
  }
  return response.json();
}
