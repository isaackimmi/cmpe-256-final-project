"""Read-only destination autocomplete. POI/model integration is deferred."""
from __future__ import annotations

from pathlib import Path
import os
import sqlite3
import unicodedata

DEFAULT_DATABASE = Path(__file__).parent / "artifacts" / "tripworld_destinations.sqlite"
LATIN_EQUIVALENTS = str.maketrans({
    "ø": "o", "ł": "l", "đ": "d", "ð": "d", "þ": "th",
    "æ": "ae", "œ": "oe", "ı": "i", "ħ": "h", "ŋ": "n", "ŧ": "t",
})
APOSTROPHES = "'’‘ʼ`´"


def normalize(text: str) -> str:
    """Fold Latin accents/case; preserve other scripts and their vowel marks."""
    text = unicodedata.normalize("NFKC", text).casefold()
    tokens, token = [], []
    latin_base = False
    for ch in text:
        if ch in APOSTROPHES:
            continue
        category = unicodedata.category(ch)
        if category.startswith("L"):
            latin_base = "LATIN" in unicodedata.name(ch, "")
            if latin_base:
                ch = "".join(c for c in unicodedata.normalize("NFKD", ch)
                             if not unicodedata.combining(c)).translate(LATIN_EQUIVALENTS)
            token.append(ch)
        elif category.startswith("N"):
            token.append(ch)
            latin_base = False
        elif category.startswith("M"):
            if token and not latin_base:
                token.append(ch)
        else:
            if token:
                tokens.append("".join(token))
                token = []
            latin_base = False
    if token:
        tokens.append("".join(token))
    return " ".join(tokens)


def query_arguments(query: str, limit: int) -> tuple[str, str, int] | None:
    if not isinstance(query, str) or len(query) > 200:
        return None
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise ValueError("limit must be an integer")
    limit = max(0, min(limit, 100))
    normalized = normalize(query)
    if not normalized or not limit:
        return None
    # Tokens contain only Unicode letters, marks, and numbers; never raw FTS syntax.
    fts = " AND ".join('"' + token + '"*' for token in normalized.split())
    return normalized, fts, limit


class Catalog:
    def __init__(self, database: str | Path | None = None):
        self.database = Path(database or os.environ.get('TRIPWORLD_DESTINATIONS_DB') or DEFAULT_DATABASE).resolve()
        try:
            self.connection = sqlite3.connect(self.database.as_uri() + "?mode=ro", uri=True)
        except sqlite3.Error as error:
            raise RuntimeError(f"Cannot open destination catalog at {self.database}. Restore the bundled SQLite artifact or set TRIPWORLD_DESTINATIONS_DB.") from error
        self.connection.row_factory = sqlite3.Row
        try:
            metadata = dict(self.connection.execute("SELECT key,value FROM build_metadata"))
            if metadata.get('scope') != 'destinations_only' or metadata.get('schema_version') != '2':
                raise RuntimeError(f"Unsupported destination catalog at {self.database}; expected destination-only schema version 2.")
            self.connection.execute(
                "SELECT count(*) FROM destination_search WHERE destination_search MATCH ?",
                ('"fts5probe"',),
            ).fetchone()
            self.country_names = [row[0] for row in self.connection.execute(
                "SELECT DISTINCT normalized_country FROM destination_aliases WHERE normalized_country<>'' ORDER BY length(normalized_country) DESC"
            )]
        except sqlite3.Error as error:
            self.connection.close()
            raise RuntimeError(f"Invalid destination catalog at {self.database}; a validated schema version 2 database and SQLite FTS5 support are required.") from error
        except BaseException:
            self.connection.close()
            raise

    def close(self) -> None:
        self.connection.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def get_destination(self, region_id: str) -> dict | None:
        row = self.connection.execute(
            "SELECT * FROM destinations WHERE region_id=?", (region_id,),
        ).fetchone()
        return dict(row) if row else None

    def search_destinations(self, query: str, limit: int = 10) -> list[dict]:
        return self.search_page(query, limit=limit)["items"]

    def search_page(self, query: str, limit: int = 20, offset: int = 0) -> dict:
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ValueError("offset must be a nonnegative integer")
        if offset >= 2**63:
            return {"items": [], "next_offset": None}
        arguments = query_arguments(query, limit)
        if isinstance(query, str) and len(query) <= 200 and not query.strip():
            if isinstance(limit, bool) or not isinstance(limit, int):
                raise ValueError("limit must be an integer")
            limit = max(0, min(limit, 100))
            if not limit:
                return {"items": [], "next_offset": None}
            rows = self.connection.execute("""
                SELECT region_id,city_name,country_name,canonical_metro_label,
                       label_missing,source_trip_count,city_name AS matched_name,
                       NULL AS matched_alias
                FROM destinations
                ORDER BY normalized_name,country_name,region_id
                LIMIT ? OFFSET ?
            """, (limit + 1, offset)).fetchall()
            return self._page(rows, limit, offset)
        if arguments is None:
            return {"items": [], "next_offset": None}
        normalized, fts, limit = arguments
        # Keep country words in FTS filtering, but rank the requested city name
        # itself as exact (e.g. London United Kingdom before City of London).
        name_query = normalized
        for country in self.country_names:
            if normalized.endswith(" " + country):
                name_query = normalized[:-len(country)-1]
                break
        rows = self.connection.execute("""
            WITH hits AS (
                SELECT a.*, row_number() OVER (
                    PARTITION BY a.region_id
                    ORDER BY (a.normalized_name = ?) DESC,
                             (a.normalized_name = ?) DESC,
                             (a.normalized_name LIKE ?) DESC, a.is_canonical DESC, a.name
                ) AS hit_rank,
                (a.normalized_name = ? OR a.normalized_name = ?) AS exact,
                (a.normalized_name LIKE ?) AS prefix
                FROM destination_search s JOIN destination_aliases a ON a.id = s.rowid
                WHERE destination_search MATCH ?
            )
            SELECT d.region_id,d.city_name,d.country_name,d.canonical_metro_label,
                   d.label_missing,d.source_trip_count,h.name AS matched_name,
                   CASE WHEN h.is_canonical = 0 THEN h.name END AS matched_alias
            FROM hits h JOIN destinations d ON d.region_id = h.region_id
            WHERE h.hit_rank = 1
            ORDER BY h.exact DESC, (d.normalized_name = ?) DESC,
                     (d.normalized_name = ?) DESC, h.prefix DESC, (d.normalized_name LIKE ?) DESC,
                     d.city_name, d.country_name, d.region_id
            LIMIT ? OFFSET ?
        """, (normalized, name_query, name_query + "%", normalized, name_query, name_query + "%", fts,
              normalized, name_query, name_query + "%", limit + 1, offset)).fetchall()
        return self._page(rows, limit, offset)

    @staticmethod
    def _page(rows, limit, offset):
        return {
            "items": [dict(row) for row in rows[:limit]],
            "next_offset": offset + limit if len(rows) > limit else None,
        }
