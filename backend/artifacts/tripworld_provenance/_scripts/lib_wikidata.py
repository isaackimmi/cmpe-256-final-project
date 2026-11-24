"""
Tiny Wikidata helper used by the Trip World build pipeline.

Two entry points:
  - sparql(query)            -> list[dict]    (POSTs to the public SPARQL endpoint)
  - get_entity(qid)          -> dict          (REST lookup; returns labels + claims)
  - p131_chain(qid, depth=8) -> list[str]     (transitive parents up the P131 ladder)

Network access is required. Polite throttling: ~3 requests/sec.
"""
from __future__ import annotations
import json, time, urllib.parse, urllib.request, gzip, ssl
from typing import Iterable

UA = "RQ3-clean-pipeline/1.0 (research; contact: rq3-bench@example.org)"
_LAST_CALL = [0.0]
_MIN_GAP = 0.30  # seconds between requests

_ssl = ssl.create_default_context()


def _throttle():
    gap = time.time() - _LAST_CALL[0]
    if gap < _MIN_GAP:
        time.sleep(_MIN_GAP - gap)
    _LAST_CALL[0] = time.time()


def _http_get(url: str, accept: str = "application/json") -> bytes:
    _throttle()
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept,
                                                "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=60, context=_ssl) as r:
        body = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            body = gzip.decompress(body)
        return body


def _http_post(url: str, body: str, ct: str = "application/sparql-query",
               accept: str = "application/sparql-results+json") -> bytes:
    _throttle()
    req = urllib.request.Request(url, data=body.encode("utf-8"),
                                  headers={"User-Agent": UA,
                                            "Content-Type": ct,
                                            "Accept": accept,
                                            "Accept-Encoding": "gzip"},
                                  method="POST")
    with urllib.request.urlopen(req, timeout=120, context=_ssl) as r:
        body = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            body = gzip.decompress(body)
        return body


def sparql(query: str, retries: int = 3) -> list[dict]:
    """Run a SPARQL query against query.wikidata.org and return the bindings."""
    url = "https://query.wikidata.org/sparql"
    last = None
    for k in range(retries):
        try:
            raw = _http_post(url, query)
            return json.loads(raw)["results"]["bindings"]
        except Exception as e:
            last = e
            time.sleep(2 + 4 * k)
    raise last


def get_entity(qid: str) -> dict:
    """Fetch raw Wikidata JSON for a single QID via Special:EntityData."""
    qid = qid.replace("wd:", "")
    url = f"https://www.wikidata.org/wiki/Special:EntityData/{qid}.json"
    for k in range(3):
        try:
            raw = _http_get(url)
            data = json.loads(raw)
            return list(data["entities"].values())[0]
        except Exception:
            time.sleep(2 + 3 * k)
    raise RuntimeError(f"failed to fetch {qid}")


def p131_chain(qid: str, max_depth: int = 8) -> list[str]:
    """Walk the 'located in administrative entity' (P131) chain upward.

    Returns ordered ancestor QIDs starting from the immediate parent.
    Stops at the first cycle / missing P131 / depth limit.
    """
    seen = {qid.replace("wd:", "")}
    chain: list[str] = []
    cur = qid.replace("wd:", "")
    for _ in range(max_depth):
        try:
            ent = get_entity(cur)
        except Exception:
            break
        claims = ent.get("claims", {}).get("P131", [])
        if not claims:
            break
        # Take the first non-deprecated parent
        parent = None
        for c in claims:
            if c.get("rank") == "deprecated":
                continue
            try:
                parent = c["mainsnak"]["datavalue"]["value"]["id"]
                break
            except (KeyError, TypeError):
                continue
        if not parent or parent in seen:
            break
        seen.add(parent)
        chain.append(parent)
        cur = parent
    return chain


def labels_batch(qids: Iterable[str]) -> dict[str, str]:
    """Fetch English labels (with Japanese / Turkish / Arabic fallbacks) for a batch of QIDs."""
    qids = [q.replace("wd:", "") for q in qids]
    out: dict[str, str] = {}
    BATCH = 50
    for i in range(0, len(qids), BATCH):
        batch = qids[i:i + BATCH]
        values = " ".join(f"wd:{q}" for q in batch)
        q = f"""
SELECT ?q ?qLabel WHERE {{
  VALUES ?q {{ {values} }}
  SERVICE wikibase:label {{
    bd:serviceParam wikibase:language "en,ja,tr,ar,es,zh,fr,de" .
  }}
}}
"""
        try:
            for r in sparql(q):
                qid = r["q"]["value"].rsplit("/", 1)[-1]
                out[qid] = r.get("qLabel", {}).get("value", "")
        except Exception as e:
            print(f"  labels_batch failed for batch {i}: {e}")
    return out


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        qid = sys.argv[1]
        print(f"label: {labels_batch([qid]).get(qid.replace('wd:', ''))}")
        print(f"P131 chain: {p131_chain(qid)}")
    else:
        # Quick smoke test
        print("Tokyo P131:", p131_chain("Q1490"))
        print("Yokohama-area P131:", p131_chain("Q49295377"))
        print("Suita P131:", p131_chain("Q49368443"))
        print("Şişli P131:", p131_chain("Q49371964"))
