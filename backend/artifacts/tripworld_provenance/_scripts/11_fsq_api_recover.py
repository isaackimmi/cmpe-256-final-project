"""
Stage 11 (optional): recover the remaining unresolved POIs via the FSQ Places
API.

Reads fsq_unresolved.txt (output of Stage 10 -- ~37k entries), hits
GET https://places-api.foursquare.com/places/{fsq_id} for each, and writes the
resolved metadata into _intermediate/fsq_api_resolved.parquet.  Then folds
the resolved rows into metadata/metadata_all.parquet.

Requires a Foursquare Places API key:
  export FSQ_API_KEY=fsq3xxxxxxxxxxxxxxxxxxxxxxxx
or pass --api-key on the command line.

Rate-limit / retry policy
-------------------------
* Default 5 concurrent requests, 250 ms inter-request delay (~20 req/s).
  Adjust with --concurrency / --delay.
* On HTTP 429: exponential backoff up to --max-backoff seconds.
* On HTTP 404: POI is permanently gone; record empty row with status='gone'.
* On HTTP 5xx: retry up to 3 times before recording status='error'.

Output
------
* _intermediate/fsq_api_resolved.parquet   (one row per requested ID + status)
* metadata/metadata_all.parquet            (rewritten with the new rows merged)
* fsq_unresolved.txt                       (rewritten with only POIs that
                                            failed permanently)
"""
from __future__ import annotations
import argparse, asyncio, json, os, ssl, sys, time
from pathlib import Path
from typing import Iterable
import urllib.parse
import os

ROOT = Path(os.environ.get("TRIP_WORLD_ROOT", Path(__file__).resolve().parent.parent))
META = ROOT / "metadata" / "metadata_all.parquet"
UNRES_IN  = ROOT / "fsq_unresolved.txt"
UNRES_OUT = ROOT / "fsq_unresolved.txt"
RESOLVED  = ROOT / "_intermediate" / "fsq_api_resolved.parquet"
CHECKPOINT = ROOT / "_intermediate" / "fsq_api_checkpoint.jsonl"  # incremental, append-only

API_BASE = "https://places-api.foursquare.com/places"
SERVICE_ACCOUNT_ID = "fsq3"     # marker for fsq_meta_source

_ssl = ssl.create_default_context()


class KeyPool:
    """Round-robin pool of API keys with dead-key tracking.

    A key is marked DEAD when the API responds with HTTP 402 OR a 429 whose
    body contains 'no API credits' (Foursquare's free-tier exhaustion message).
    Other 429s (true rate-limiting) trigger backoff but keep the key alive.
    """
    def __init__(self, keys: list[str]):
        self.keys = list(dict.fromkeys(k.strip() for k in keys if k.strip()))
        self.alive = list(self.keys)
        self._cursor = 0

    @property
    def n_alive(self) -> int:
        return len(self.alive)

    @property
    def n_total(self) -> int:
        return len(self.keys)

    def next_key(self) -> str | None:
        """Return any live key (round-robin). None if pool is empty."""
        if not self.alive:
            return None
        k = self.alive[self._cursor % len(self.alive)]
        self._cursor += 1
        return k

    def mark_dead(self, key: str, reason: str = "") -> None:
        if key in self.alive:
            self.alive.remove(key)
            tail = key[-8:]
            print(f"  [key pool] key ...{tail} marked dead "
                  f"({reason}); alive={self.n_alive}/{self.n_total}",
                  flush=True)


def _is_no_credits(status: int, body_text: str) -> bool:
    if status == 402:
        return True
    if status == 429 and ("no API credits" in body_text
                           or "Purchasing credits" in body_text):
        return True
    return False


async def fetch_one(session, sem, fsq_id: str, pool: KeyPool, delay: float,
                     max_backoff: float) -> dict:
    """Fetch one FSQ place by ID with retry/backoff and key rotation."""
    bare = fsq_id.replace("foursquare:", "")
    url = f"{API_BASE}/{urllib.parse.quote(bare)}"
    backoff = 1.0
    for attempt in range(6):
        api_key = pool.next_key()
        if api_key is None:
            return {"fsq_place_id": fsq_id, "status": "no_credits", "raw": None}
        auth = api_key if api_key.lower().startswith("bearer ") else f"Bearer {api_key}"
        headers = {"Authorization": auth,
                   "X-Places-Api-Version": "2025-06-17",
                   "Accept": "application/json"}
        async with sem:
            await asyncio.sleep(delay)
            try:
                async with session.get(url, headers=headers, ssl=_ssl,
                                         timeout=30) as r:
                    if r.status == 200:
                        body = await r.json()
                        return {"fsq_place_id": fsq_id, "status": "ok",
                                "raw": body}
                    elif r.status == 404:
                        return {"fsq_place_id": fsq_id, "status": "gone",
                                "raw": None}
                    elif r.status in (402, 429):
                        body_text = await r.text()
                        if _is_no_credits(r.status, body_text):
                            pool.mark_dead(api_key, f"HTTP {r.status} no_credits")
                            continue  # try next key on next attempt
                        retry_after = float(r.headers.get("Retry-After", backoff))
                        await asyncio.sleep(min(retry_after, max_backoff))
                        backoff = min(backoff * 2, max_backoff)
                        continue
                    elif 500 <= r.status < 600:
                        await asyncio.sleep(min(backoff, max_backoff))
                        backoff = min(backoff * 2, max_backoff)
                        continue
                    else:
                        body = await r.text()
                        return {"fsq_place_id": fsq_id,
                                "status": f"http_{r.status}",
                                "raw": {"error": body[:500]}}
            except Exception as e:
                await asyncio.sleep(min(backoff, max_backoff))
                backoff = min(backoff * 2, max_backoff)
    return {"fsq_place_id": fsq_id, "status": "error", "raw": None}


async def driver(ids: list[str], pool: KeyPool, concurrency: int, delay: float,
                  max_backoff: float, checkpoint_path: Path,
                  progress_every: int = 500):
    import aiohttp
    connector = aiohttp.TCPConnector(limit=concurrency, force_close=False)
    sem = asyncio.Semaphore(concurrency)
    out = []
    n = len(ids)
    t0 = time.time()
    last_log = 0
    # Append-only JSONL so we can resume mid-run if interrupted.
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    with open(checkpoint_path, "a", buffering=1) as ckpt:
        async with aiohttp.ClientSession(connector=connector) as session:
            tasks = [fetch_one(session, sem, fsq_id, pool, delay, max_backoff)
                     for fsq_id in ids]
            for i, coro in enumerate(asyncio.as_completed(tasks), 1):
                r = await coro
                out.append(r)
                ckpt.write(json.dumps(r, ensure_ascii=False) + "\n")
                if i - last_log >= progress_every:
                    last_log = i
                    rate = i / (time.time() - t0 + 1e-9)
                    eta = (n - i) / max(rate, 1e-9)
                    ok = sum(1 for x in out if x["status"] == "ok")
                    gone = sum(1 for x in out if x["status"] == "gone")
                    nc = sum(1 for x in out if x["status"] == "no_credits")
                    err = i - ok - gone - nc
                    print(f"  [{time.time()-t0:5.0f}s] {i:>6}/{n} "
                          f"ok={ok} gone={gone} nc={nc} err={err}  "
                          f"{rate:.1f} req/s  ETA={eta/60:.1f} min  "
                          f"keys_alive={pool.n_alive}/{pool.n_total}", flush=True)
                if pool.n_alive == 0:
                    print(f"  !! all keys exhausted; cancelling remaining {n-i} tasks",
                          flush=True)
                    break
    return out


def fsq_payload_to_row(p: dict, fsq_id: str) -> dict:
    """Map an FSQ Places API (2025-06-17 version) response onto our schema.

    The new API returns lat/lon at the top level (not nested under geocodes),
    and categories use `fsq_category_id`/`name` keys.
    """
    if not p:
        return {"fsq_place_id": fsq_id, "has_fsq_metadata": False,
                "fsq_meta_source": "fsq_api_gone"}
    loc = p.get("location", {}) or {}
    cats = p.get("categories", []) or []
    facebook_id = (p.get("social_media") or {}).get("facebook_id")
    try:
        facebook_id = int(facebook_id) if facebook_id else None
    except (TypeError, ValueError):
        facebook_id = None
    return {
        "fsq_place_id": fsq_id,
        "fsq_name": p.get("name"),
        "fsq_latitude": p.get("latitude"),
        "fsq_longitude": p.get("longitude"),
        "fsq_address": loc.get("address"),
        "fsq_locality": loc.get("locality"),
        "fsq_region": loc.get("region"),
        "fsq_country": loc.get("country"),
        "fsq_postcode": loc.get("postcode"),
        "fsq_formatted_address": loc.get("formatted_address"),
        "fsq_category_ids": [str(c.get("fsq_category_id")) for c in cats
                              if c.get("fsq_category_id") is not None],
        "fsq_category_labels": [c.get("name") for c in cats if c.get("name")],
        "fsq_website": p.get("website"),
        "fsq_tel": p.get("tel"),
        "fsq_email": p.get("email"),
        "fsq_facebook_id": facebook_id,
        "fsq_instagram":   (p.get("social_media") or {}).get("instagram"),
        "fsq_twitter":     (p.get("social_media") or {}).get("twitter"),
        "fsq_date_created":   (p.get("date_created") or None),
        "fsq_date_refreshed": (p.get("date_refreshed") or None),
        "fsq_date_closed":    (p.get("date_closed") or None),
        "fsq_meta_source": "fsq_api_2025",
        "has_fsq_metadata": True,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--api-key", action="append", default=[],
                     help="FSQ Places API bearer token (repeat for multiple keys)")
    ap.add_argument("--api-keys-file",
                     help="path to a file containing one bearer token per line")
    ap.add_argument("--concurrency", type=int, default=5)
    ap.add_argument("--delay", type=float, default=0.20,
                     help="seconds between consecutive requests per worker")
    ap.add_argument("--max-backoff", type=float, default=30.0)
    ap.add_argument("--limit", type=int, default=0,
                     help="if >0, only process the first N unresolved IDs (smoke test)")
    args = ap.parse_args()

    keys: list[str] = list(args.api_key)
    if args.api_keys_file:
        keys.extend(l.strip() for l in Path(args.api_keys_file).read_text().splitlines()
                    if l.strip() and not l.strip().startswith("#"))
    if not keys and os.environ.get("FSQ_API_KEY"):
        keys.append(os.environ["FSQ_API_KEY"].strip())
    keys = list(dict.fromkeys(keys))  # de-dup, preserve order
    if not keys:
        print("ERROR: no FSQ API key. Pass --api-key, --api-keys-file or "
              "set $FSQ_API_KEY.")
        sys.exit(1)
    pool = KeyPool(keys)
    print(f"Loaded {pool.n_total} API key(s) into pool "
          f"(masked: {[k[-8:] for k in pool.keys]})")

    try:
        import aiohttp  # noqa
    except ImportError:
        print("ERROR: aiohttp not installed. Run: pip install aiohttp")
        sys.exit(1)
    import duckdb
    import pyarrow as pa, pyarrow.parquet as pq

    ids = [l.strip() for l in UNRES_IN.read_text().splitlines() if l.strip()]

    # Resume support: skip any IDs that already appear in the JSONL checkpoint
    # with a TERMINAL status (ok / gone). Transient errors will be retried.
    already = {}
    if CHECKPOINT.exists():
        with open(CHECKPOINT) as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if rec.get("status") in ("ok", "gone"):
                    already[rec["fsq_place_id"]] = rec
        if already:
            print(f"Resumed checkpoint: skipping {len(already):,} already-resolved ids")
    ids = [i for i in ids if i not in already]

    if args.limit:
        ids = ids[:args.limit]
    print(f"Will resolve {len(ids):,} POI IDs via FSQ Places API")
    print(f"  concurrency={args.concurrency}  delay={args.delay}s  "
          f"target rate ~{args.concurrency/args.delay:.1f} req/s")
    print()

    raw_new = asyncio.run(driver(ids, pool, args.concurrency, args.delay,
                                  args.max_backoff, CHECKPOINT))
    raw = list(already.values()) + raw_new

    # Build rows
    rows = []
    n_ok = n_gone = n_err = 0
    for r in raw:
        st = r["status"]
        if st == "ok":
            rows.append(fsq_payload_to_row(r["raw"], r["fsq_place_id"]))
            n_ok += 1
        elif st == "gone":
            rows.append({"fsq_place_id": r["fsq_place_id"],
                          "fsq_meta_source": "fsq_api_gone",
                          "has_fsq_metadata": False})
            n_gone += 1
        else:
            rows.append({"fsq_place_id": r["fsq_place_id"],
                          "fsq_meta_source": f"fsq_api_{st}",
                          "has_fsq_metadata": False})
            n_err += 1
    print(f"\nRESULT: ok={n_ok}  gone={n_gone}  err={n_err}")

    # Write resolved table
    RESOLVED.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows), RESOLVED, compression="zstd")
    print(f"wrote {RESOLVED} ({RESOLVED.stat().st_size/1e6:.1f} MB)")

    # Fold into metadata_all.parquet
    print("merging into metadata_all.parquet ...")
    con = duckdb.connect()
    con.execute("PRAGMA threads=32")
    con.execute("SET memory_limit='32GB'")
    META_TMP = META.with_suffix(".tmp.parquet")
    con.execute(f"""
COPY (
  -- existing rows MINUS the IDs we just refetched
  SELECT * FROM '{META}'
  WHERE fsq_place_id NOT IN (SELECT fsq_place_id FROM '{RESOLVED}')
  UNION ALL BY NAME
  -- the new rows (use CAST/COALESCE to keep schema compatible)
  SELECT
    r.fsq_place_id,
    NULL AS benchmark_name,
    NULL AS benchmark_locality,
    NULL AS benchmark_venue_category,
    NULL AS benchmark_venue_schema,
    r.fsq_name, r.fsq_latitude, r.fsq_longitude,
    r.fsq_address, r.fsq_locality, r.fsq_region, r.fsq_country,
    r.fsq_postcode, r.fsq_formatted_address,
    r.fsq_category_ids, r.fsq_category_labels,
    r.fsq_website, r.fsq_tel, r.fsq_email,
    r.fsq_facebook_id, r.fsq_instagram, r.fsq_twitter,
    r.fsq_date_created, r.fsq_date_refreshed, r.fsq_date_closed,
    r.fsq_meta_source, r.has_fsq_metadata,
    NULL AS google_cid, NULL AS google_name,
    NULL AS google_full_address, NULL AS google_address,
    NULL AS google_website, NULL AS google_rating, NULL AS google_num_reviews,
    NULL AS google_categories, NULL AS google_place_id, NULL AS google_gmaps_url,
    'none' AS google_meta_source,
    FALSE AS has_google_metadata
  FROM '{RESOLVED}' r
) TO '{META_TMP}' (FORMAT PARQUET, COMPRESSION 'zstd', ROW_GROUP_SIZE 200000)
""")
    META.unlink()
    META_TMP.rename(META)
    n_total = con.execute(f"SELECT COUNT(*) FROM '{META}'").fetchone()[0]
    n_with_fsq = con.execute(f"SELECT SUM(CASE WHEN has_fsq_metadata THEN 1 ELSE 0 END) FROM '{META}'").fetchone()[0]
    n_with_coords = con.execute(f"SELECT SUM(CASE WHEN fsq_latitude IS NOT NULL THEN 1 ELSE 0 END) FROM '{META}'").fetchone()[0]
    print(f"metadata_all.parquet rewritten: {n_total:,} rows, "
          f"{n_with_fsq:,} with FSQ ({n_with_fsq/n_total*100:.1f}%), "
          f"{n_with_coords:,} with coords ({n_with_coords/n_total*100:.1f}%)")

    # Update unresolved list: keep IDs we did NOT attempt this run (i.e. those
    # left over because of --limit), and add back the IDs that errored out.
    attempted = {r["fsq_place_id"] for r in raw}
    failed    = {r["fsq_place_id"] for r in raw if r["status"] not in ("ok", "gone")}
    all_unres_now = [i for i in
                     [l.strip() for l in UNRES_IN.read_text().splitlines() if l.strip()]
                     if (i not in attempted) or (i in failed)]
    UNRES_OUT.write_text("\n".join(all_unres_now))
    print(f"  remaining unresolved -> {UNRES_OUT}  ({len(all_unres_now):,} ids)")


if __name__ == "__main__":
    main()
