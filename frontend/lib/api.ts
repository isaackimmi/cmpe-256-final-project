class HttpError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

export function shouldRetryRequest(failureCount: number, error: Error) {
  if (failureCount >= 1) return false;
  if (error instanceof HttpError) {
    return error.status === 408 || error.status === 429 || error.status >= 500;
  }
  return error instanceof TypeError;
}

export async function fetchJson<T>(
  url: string,
  options: RequestInit,
): Promise<T> {
  const response = await fetch(url, options);
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    const message = body?.error ?? body?.detail;
    throw new HttpError(
      typeof message === "string"
        ? message
        : `Request failed (${response.status})`,
      response.status,
    );
  }
  return response.json();
}
