"""TripWorld Data Understanding & Exploratory Data Analysis (EDA) script.

Queries the local TripWorld core Parquet files with DuckDB and writes a
structured JSON summary (`reports/tripworld_eda_summary.json`) covering:
- Dataset table schemas, row counts, null/missingness rates
- Global & European geographic coverage (countries, top cities, city pairs)
- Lisbon & Madrid deep-dive (POIs, museums/art galleries, cross-city trips)
- Real sample traveler record (home history -> destination trip)
- Category & Schema.org taxonomy breakdown
- Data quality & modeling readiness insights (sparsity, Google metadata coverage,
  review counts, distribution of home vs. travel check-ins)
"""

from __future__ import annotations

import json
from pathlib import Path
import duckdb

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data" / "tripworld"
OUT_PATH = ROOT / "reports" / "tripworld_eda_summary.json"


def query_dicts(con: duckdb.DuckDBPyConnection, sql: str) -> list[dict]:
    rel = con.sql(sql)
    cols = rel.columns
    rows = rel.fetchall()
    result = []
    for row in rows:
        item = {}
        for col, val in zip(cols, row):
            if hasattr(val, "isoformat"):
                val = val.isoformat()
            item[col] = val
        result.append(item)
    return result


def main() -> None:
    con = duckdb.connect()
    con.execute(f"""
        CREATE VIEW travel AS SELECT * FROM '{DATA_DIR}/travel_behaviors.parquet';
        CREATE VIEW pois AS SELECT * FROM '{DATA_DIR}/pois.parquet';
        CREATE VIEW meta AS SELECT * FROM '{DATA_DIR}/metadata/metadata_all.parquet';
        CREATE VIEW attrs AS SELECT * FROM '{DATA_DIR}/metadata/place_attributes.parquet';
        CREATE VIEW regions AS SELECT * FROM '{DATA_DIR}/region_labels.parquet';
    """)

    summary: dict = {}

    # 1. Schemas & row counts
    tables = ["travel", "pois", "meta", "attrs", "regions"]
    summary["tables"] = {}
    for tbl in tables:
        cnt = con.sql(f"SELECT COUNT(*) FROM {tbl}").fetchall()[0][0]
        cols = query_dicts(con, f"DESCRIBE {tbl}")
        summary["tables"][tbl] = {
            "row_count": cnt,
            "columns": [{"name": c["column_name"], "type": c["column_type"]} for c in cols],
        }

    # 2. Headline metrics
    summary["headline"] = query_dicts(con, """
        SELECT
            COUNT(*) AS total_trip_records,
            COUNT(DISTINCT user_id) AS unique_travelers,
            COUNT(DISTINCT r_h) AS unique_home_cities,
            COUNT(DISTINCT r_o) AS unique_dest_cities,
            SUM(n_home_ci) AS total_home_checkins_sum,
            SUM(n_travel_ci) AS total_travel_checkins_sum,
            ROUND(AVG(n_home_ci), 2) AS avg_home_ci,
            MEDIAN(n_home_ci) AS median_home_ci,
            ROUND(AVG(n_travel_ci), 2) AS avg_travel_ci,
            MEDIAN(n_travel_ci) AS median_travel_ci,
            QUANTILE_CONT(n_travel_ci, 0.90) AS p90_travel_ci,
            MAX(n_travel_ci) AS max_travel_ci
        FROM travel
    """)[0]

    # Unique home checkins per user (since a user can have multiple destination records)
    summary["user_stats"] = query_dicts(con, """
        WITH per_user AS (
            SELECT
                user_id,
                COUNT(*) AS num_dest_cities,
                MAX(n_home_ci) AS home_ci,
                SUM(n_travel_ci) AS total_travel_ci
            FROM travel
            GROUP BY user_id
        )
        SELECT
            COUNT(*) AS unique_users,
            ROUND(AVG(num_dest_cities), 2) AS avg_dest_cities_per_user,
            MEDIAN(num_dest_cities) AS median_dest_cities_per_user,
            MAX(num_dest_cities) AS max_dest_cities_per_user,
            SUM(home_ci) AS deduplicated_home_checkins,
            SUM(total_travel_ci) AS total_travel_checkins,
            COUNT(*) FILTER (WHERE total_travel_ci >= 3) AS users_ge_3_travel_ci,
            COUNT(*) FILTER (WHERE total_travel_ci >= 5) AS users_ge_5_travel_ci,
            COUNT(*) FILTER (WHERE num_dest_cities >= 2) AS users_ge_2_dest_cities
        FROM per_user
    """)[0]

    # 3. POI enrichment & quality stats
    summary["poi_quality"] = query_dicts(con, """
        SELECT
            COUNT(*) AS total_pois,
            COUNT(DISTINCT locality) AS unique_localities,
            COUNT(*) FILTER (WHERE has_google_metadata) AS with_google_meta,
            ROUND(100.0 * COUNT(*) FILTER (WHERE has_google_metadata) / COUNT(*), 2) AS pct_google_meta,
            COUNT(*) FILTER (WHERE has_reviews) AS with_reviews,
            ROUND(100.0 * COUNT(*) FILTER (WHERE has_reviews) / COUNT(*), 2) AS pct_reviews,
            COUNT(*) FILTER (WHERE google_name IS NOT NULL AND google_name != '') AS with_google_name,
            COUNT(*) FILTER (WHERE google_rating IS NOT NULL) AS with_google_rating,
            ROUND(AVG(google_rating), 2) AS avg_google_rating,
            SUM(n_reviews) AS total_reviews_sum,
            SUM(n_reviews_with_text) AS total_reviews_with_text_sum,
            MEDIAN(n_checkins) AS median_poi_checkins,
            ROUND(AVG(n_checkins), 2) AS avg_poi_checkins
        FROM pois
    """)[0]

    summary["meta_quality"] = query_dicts(con, """
        SELECT
            COUNT(*) AS total_rows,
            COUNT(*) FILTER (WHERE fsq_name IS NOT NULL AND fsq_name != '') AS with_fsq_name,
            COUNT(*) FILTER (WHERE fsq_latitude IS NOT NULL AND fsq_longitude IS NOT NULL) AS with_gps,
            COUNT(*) FILTER (WHERE fsq_date_closed IS NOT NULL) AS closed_pois,
            COUNT(*) FILTER (WHERE google_name IS NOT NULL OR fsq_name IS NOT NULL) AS with_any_name
        FROM meta
    """)[0]

    # 4. Top countries by outbound & inbound trips
    summary["top_countries_dest"] = query_dicts(con, """
        SELECT
            r.country_name,
            COUNT(*) AS trips,
            COUNT(DISTINCT t.user_id) AS unique_visitors,
            COUNT(DISTINCT t.r_o) AS cities_in_country
        FROM travel t
        JOIN regions r ON t.r_o = r.region_id
        GROUP BY r.country_name
        ORDER BY trips DESC
        LIMIT 15
    """)

    # 5. Top destination cities globally
    summary["top_dest_cities"] = query_dicts(con, """
        SELECT
            r.region_id,
            r.city_name,
            r.country_name,
            COUNT(*) AS inbound_trips,
            SUM(t.n_travel_ci) AS travel_checkins,
            ROUND(AVG(t.n_travel_ci), 2) AS avg_ci_per_trip
        FROM travel t
        JOIN regions r ON t.r_o = r.region_id
        GROUP BY r.region_id, r.city_name, r.country_name
        ORDER BY inbound_trips DESC
        LIMIT 15
    """)

    # 6. Top city-to-city corridors globally
    summary["top_corridors"] = query_dicts(con, """
        SELECT
            rh.city_name AS home_city,
            rh.country_name AS home_country,
            ro.city_name AS dest_city,
            ro.country_name AS dest_country,
            COUNT(*) AS trips,
            SUM(t.n_travel_ci) AS travel_checkins
        FROM travel t
        JOIN regions rh ON t.r_h = rh.region_id
        JOIN regions ro ON t.r_o = ro.region_id
        GROUP BY 1, 2, 3, 4
        ORDER BY trips DESC
        LIMIT 15
    """)

    # 7. Top European destination cities
    europe_countries = (
        "'United Kingdom','France','Spain','Italy','Germany','Portugal','Netherlands',"
        "'Belgium','Switzerland','Austria','Greece','Czech Republic','Poland','Sweden',"
        "'Norway','Denmark','Finland','Ireland','Hungary','Croatia','Romania','Bulgaria',"
        "'Serbia','Slovakia','Slovenia','Estonia','Latvia','Lithuania','Iceland','Luxembourg',"
        "'Ukraine','Russia','Turkey'"
    )
    summary["top_europe_cities"] = query_dicts(con, f"""
        SELECT
            r.region_id,
            r.city_name,
            r.country_name,
            COUNT(*) AS inbound_trips,
            SUM(t.n_travel_ci) AS travel_checkins,
            (SELECT COUNT(*) FROM pois p WHERE p.locality = r.region_id) AS total_pois
        FROM travel t
        JOIN regions r ON t.r_o = r.region_id
        WHERE r.country_name IN ({europe_countries})
        GROUP BY r.region_id, r.city_name, r.country_name
        ORDER BY inbound_trips DESC
        LIMIT 15
    """)

    # 8. Lisbon & Madrid deep dive
    summary["lisbon_madrid_cities"] = query_dicts(con, """
        SELECT
            r.region_id,
            r.city_name,
            r.country_name,
            (SELECT COUNT(*) FROM pois p WHERE p.locality = r.region_id) AS total_pois,
            (SELECT COUNT(*) FROM pois p WHERE p.locality = r.region_id
                AND (LOWER(COALESCE(p.venue_category, '')) LIKE '%museum%'
                  OR LOWER(COALESCE(p.venue_category, '')) LIKE '%art%'
                  OR LOWER(COALESCE(p.venue_schema, '')) LIKE '%museum%'
                  OR LOWER(COALESCE(p.venue_schema, '')) LIKE '%art%')) AS museum_art_pois,
            (SELECT COUNT(*) FROM travel t WHERE t.r_h = r.region_id) AS outbound_trips,
            (SELECT COUNT(*) FROM travel t WHERE t.r_o = r.region_id) AS inbound_trips,
            (SELECT COALESCE(SUM(t.n_travel_ci), 0) FROM travel t WHERE t.r_o = r.region_id) AS inbound_checkins
        FROM regions r
        WHERE LOWER(r.city_name) IN ('lisbon', 'madrid', 'barcelona', 'paris', 'london', 'rome', 'amsterdam', 'berlin')
        ORDER BY inbound_trips DESC
    """)

    summary["lisbon_madrid_pair"] = query_dicts(con, """
        SELECT
            rh.city_name AS home_city,
            ro.city_name AS dest_city,
            COUNT(*) AS trips,
            SUM(t.n_travel_ci) AS travel_checkins
        FROM travel t
        JOIN regions rh ON t.r_h = rh.region_id
        JOIN regions ro ON t.r_o = ro.region_id
        WHERE (LOWER(rh.city_name) = 'lisbon' AND LOWER(ro.city_name) = 'madrid')
           OR (LOWER(rh.city_name) = 'madrid' AND LOWER(ro.city_name) = 'lisbon')
           OR (LOWER(rh.city_name) = 'madrid' AND LOWER(ro.city_name) = 'barcelona')
           OR (LOWER(rh.city_name) = 'barcelona' AND LOWER(ro.city_name) = 'madrid')
           OR (LOWER(rh.city_name) = 'london' AND LOWER(ro.city_name) = 'paris')
           OR (LOWER(rh.city_name) = 'paris' AND LOWER(ro.city_name) = 'london')
        GROUP BY 1, 2
        ORDER BY trips DESC
    """)

    # Top Museums & Art Galleries in Lisbon and Madrid (real names!)
    summary["lisbon_museums"] = query_dicts(con, """
        SELECT
            COALESCE(p.google_name, m.fsq_name) AS name,
            p.venue_category,
            p.venue_schema,
            p.n_checkins,
            p.google_rating,
            p.google_num_reviews
        FROM pois p
        JOIN regions r ON p.locality = r.region_id
        LEFT JOIN meta m ON p.fsq_place_id = m.fsq_place_id
        WHERE LOWER(r.city_name) = 'lisbon'
          AND (LOWER(COALESCE(p.venue_category, '')) LIKE '%museum%'
            OR LOWER(COALESCE(p.venue_category, '')) LIKE '%art gallery%'
            OR LOWER(COALESCE(p.venue_schema, '')) LIKE '%museum%')
          AND COALESCE(p.google_name, m.fsq_name) IS NOT NULL
        ORDER BY p.n_checkins DESC
        LIMIT 8
    """)

    summary["madrid_museums"] = query_dicts(con, """
        SELECT
            COALESCE(p.google_name, m.fsq_name) AS name,
            p.venue_category,
            p.venue_schema,
            p.n_checkins,
            p.google_rating,
            p.google_num_reviews
        FROM pois p
        JOIN regions r ON p.locality = r.region_id
        LEFT JOIN meta m ON p.fsq_place_id = m.fsq_place_id
        WHERE LOWER(r.city_name) = 'madrid'
          AND (LOWER(COALESCE(p.venue_category, '')) LIKE '%museum%'
            OR LOWER(COALESCE(p.venue_category, '')) LIKE '%art gallery%'
            OR LOWER(COALESCE(p.venue_schema, '')) LIKE '%museum%')
          AND COALESCE(p.google_name, m.fsq_name) IS NOT NULL
        ORDER BY p.n_checkins DESC
        LIMIT 8
    """)

    # 9. Category & Schema.org breakdown
    summary["top_venue_categories"] = query_dicts(con, """
        SELECT
            venue_category,
            COUNT(*) AS poi_count,
            SUM(n_checkins) AS total_checkins,
            ROUND(AVG(google_rating), 2) AS avg_rating
        FROM pois
        WHERE venue_category IS NOT NULL
        GROUP BY venue_category
        ORDER BY total_checkins DESC
        LIMIT 15
    """)

    summary["top_venue_schemas"] = query_dicts(con, """
        SELECT
            venue_schema,
            COUNT(*) AS poi_count,
            SUM(n_checkins) AS total_checkins
        FROM pois
        WHERE venue_schema IS NOT NULL
        GROUP BY venue_schema
        ORDER BY poi_count DESC
        LIMIT 12
    """)

    # 10. Trip length distribution (travel check-ins per trip bucket)
    summary["trip_length_buckets"] = query_dicts(con, """
        SELECT
            CASE
                WHEN n_travel_ci = 1 THEN '1 check-in'
                WHEN n_travel_ci = 2 THEN '2 check-ins'
                WHEN n_travel_ci BETWEEN 3 AND 5 THEN '3-5 check-ins'
                WHEN n_travel_ci BETWEEN 6 AND 10 THEN '6-10 check-ins'
                WHEN n_travel_ci BETWEEN 11 AND 20 THEN '11-20 check-ins'
                ELSE '21+ check-ins'
            END AS bucket,
            COUNT(*) AS trips,
            MIN(n_travel_ci) AS sort_key
        FROM travel
        GROUP BY 1
        ORDER BY sort_key
    """)

    # 11. Find an illustrative real traveler who visited museums/art in one city and went to Madrid or Paris/Barcelona
    sample_rows = con.sql("""
        WITH madrid_trips AS (
            SELECT
                t.user_id,
                rh.city_name AS home_city,
                rh.country_name AS home_country,
                ro.city_name AS dest_city,
                ro.country_name AS dest_country,
                t.n_home_ci,
                t.n_travel_ci,
                t.c_h,
                t.c_o
            FROM travel t
            JOIN regions rh ON t.r_h = rh.region_id
            JOIN regions ro ON t.r_o = ro.region_id
            WHERE LOWER(ro.city_name) = 'madrid'
              AND t.n_home_ci BETWEEN 10 AND 80
              AND t.n_travel_ci BETWEEN 4 AND 15
        )
        SELECT * FROM madrid_trips
        WHERE CAST(c_h AS VARCHAR) ILIKE '%Museum%'
          AND CAST(c_o AS VARCHAR) ILIKE '%Museum%'
        LIMIT 1
    """).fetchall()

    if not sample_rows:
        sample_rows = con.sql("""
            SELECT
                t.user_id,
                rh.city_name AS home_city,
                rh.country_name AS home_country,
                ro.city_name AS dest_city,
                ro.country_name AS dest_country,
                t.n_home_ci,
                t.n_travel_ci,
                t.c_h,
                t.c_o
            FROM travel t
            JOIN regions rh ON t.r_h = rh.region_id
            JOIN regions ro ON t.r_o = ro.region_id
            WHERE t.n_home_ci BETWEEN 10 AND 60
              AND t.n_travel_ci BETWEEN 4 AND 12
              AND CAST(t.c_h AS VARCHAR) ILIKE '%Museum%'
              AND CAST(t.c_o AS VARCHAR) ILIKE '%Museum%'
            LIMIT 1
        """).fetchall()

    sample_row = sample_rows[0] if sample_rows else None

    if sample_row is not None:
        uid, hcity, hctry, dcity, dctry, nh, nt, ch_list, co_list = sample_row

        def resolve_visits(visits: list[dict], limit: int = 10) -> list[dict]:
            seen = set()
            unique_vids = []
            for v in visits:
                vid = v.get("venue_id", "")
                # Strip 'foursquare:' prefix if present
                clean_id = vid.split(":", 1)[1] if ":" in vid else vid
                if clean_id not in seen:
                    seen.add(clean_id)
                    unique_vids.append((clean_id, v))
            # Lookup names in DuckDB
            id_list = [x[0] for x in unique_vids[:limit * 2]]
            if not id_list:
                return []
            placeholders = ",".join(f"'{i}'" for i in id_list)
            rows = con.sql(f"""
                SELECT p.fsq_place_id, COALESCE(p.google_name, m.fsq_name) AS name,
                       p.venue_category, p.google_rating
                FROM pois p
                LEFT JOIN meta m ON p.fsq_place_id = m.fsq_place_id
                WHERE p.fsq_place_id IN ({placeholders})
            """).fetchall()
            name_map = {r[0]: {"name": r[1], "category": r[2], "rating": r[3]} for r in rows}
            out = []
            for clean_id, v in unique_vids:
                info = name_map.get(clean_id, {})
                out.append({
                    "venue_id": clean_id,
                    "name": info.get("name") or "(Unnamed POI)",
                    "category": info.get("category") or v.get("venue_category"),
                    "rating": info.get("rating"),
                    "ts": str(v.get("ts", "")),
                })
                if len(out) >= limit:
                    break
            return out

        # Sort museums/cultural spots first in display so the sample is readable
        summary["sample_traveler"] = {
            "user_id": str(uid),
            "home_city": f"{hcity}, {hctry}",
            "dest_city": f"{dcity}, {dctry}",
            "n_home_ci": nh,
            "n_travel_ci": nt,
            "home_sample": resolve_visits(ch_list, limit=8),
            "dest_sample": resolve_visits(co_list, limit=8),
        }

    # 12. Tourism vs non-tourism category share in travel check-ins (sample 50k trips for speed)
    summary["home_vs_travel_category_shift"] = query_dicts(con, """
        WITH home_cats AS (
            SELECT
                u.venue_category AS cat,
                COUNT(*) AS cnt
            FROM (SELECT c_h FROM travel USING SAMPLE 50000 ROWS),
            UNNEST(c_h) AS t(u)
            GROUP BY 1
        ),
        travel_cats AS (
            SELECT
                u.venue_category AS cat,
                COUNT(*) AS cnt
            FROM (SELECT c_o FROM travel USING SAMPLE 50000 ROWS),
            UNNEST(c_o) AS t(u)
            GROUP BY 1
        ),
        totals AS (
            SELECT
                (SELECT SUM(cnt) FROM home_cats) AS h_tot,
                (SELECT SUM(cnt) FROM travel_cats) AS t_tot
        )
        SELECT
            tc.cat AS category,
            ROUND(100.0 * COALESCE(hc.cnt, 0) / totals.h_tot, 3) AS home_pct,
            ROUND(100.0 * tc.cnt / totals.t_tot, 3) AS travel_pct,
            ROUND((tc.cnt / totals.t_tot) / NULLIF(COALESCE(hc.cnt, 1) / totals.h_tot, 0), 2) AS travel_lift
        FROM travel_cats tc
        LEFT JOIN home_cats hc ON tc.cat = hc.cat
        CROSS JOIN totals
        WHERE tc.cnt >= 500
          AND tc.cat IS NOT NULL
        ORDER BY travel_lift DESC
        LIMIT 12
    """)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(summary, indent=2, default=str))
    print(f"Wrote EDA summary to {OUT_PATH}")


if __name__ == "__main__":
    main()
