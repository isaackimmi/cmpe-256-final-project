import assert from "node:assert/strict";
import test from "node:test";
import { fetchJson, shouldRetryRequest } from "../lib/api.ts";

test("HTTP status determines whether a failed query can retry", async (t) => {
  for (const [status, retry] of [[422, false], [408, true], [429, true], [503, true]]) {
    await t.test(String(status), async (t) => {
      t.mock.method(globalThis, "fetch", async () =>
        Response.json({ detail: "Backend message" }, { status }),
      );
      await assert.rejects(fetchJson("/api/places/search", {}), (error) => {
        assert.equal(error.status, status);
        assert.equal(error.message, "Backend message");
        assert.equal(shouldRetryRequest(0, error), retry);
        assert.equal(shouldRetryRequest(1, error), false);
        return true;
      });
    });
  }
});

test("a network failure retries once, while cancellation does not retry", () => {
  const networkFailure = new TypeError("Failed to fetch");
  assert.equal(shouldRetryRequest(0, networkFailure), true);
  assert.equal(shouldRetryRequest(1, networkFailure), false);
  assert.equal(shouldRetryRequest(0, new DOMException("", "AbortError")), false);
});
