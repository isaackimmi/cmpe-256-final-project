"""
Build the METRO-level metro_mapping_clean.json for the Trip World build pipeline.

The a precursor build used CITY-level consolidation, which left commuter-belt
municipalities (Yokohama -> Tokyo, Suita -> Osaka, ...) as separate
"destinations".  This produced ~14% phantom intra-metro travel records.
The Trip World build pipeline uses METRO-level consolidation: any administrative entity
inside a known metropolitan area collapses to a single anchor QID.

Sources:
  1) Optional pre-existing metro map provided via an existing metro map seed (optional, supplied via the --existing CLI flag; carried over verbatim and only extended) (carried through if set; only adds, never removes).
  2) Hand-curated METRO_DEFINITIONS giving each anchor metro and the cities,
     districts and prefectures inside its commuter belt.  Member QIDs are
     drawn from Wikidata (verified by name lookup -- see _scripts/lookup_qids.txt).
  3) SPARQL P131+ descendants of each anchor (gathers any sub-municipal entity
     reachable via "located in administrative entity" within the metro).
  4) Foursquare-internal "Q49xxxxxxx / Q27347xxx / Q35xxxxxxx" QIDs that lack
     proper P131 chains -- explicitly listed below by raw_QID -> metro_QID.

Output: $TRIP_WORLD_ROOT/metro_mapping_clean.json
"""
from __future__ import annotations
import argparse, csv, json, time, collections
from pathlib import Path
from lib_wikidata import sparql, labels_batch
import os

# ---------------------------------------------------------------- METRO DEFINITIONS

# Anchor metro QID -> human-readable name and member sub-entity QIDs.
# Each member is a Wikidata QID (city, district, ward, prefecture, governorate)
# that should collapse to the anchor.  Members include:
#   * the anchor itself (no-op identity)
#   * core city wards / boroughs / special wards
#   * commuter-belt municipalities
#   * the prefecture(s)/province(s)/state(s) that *primarily* serve the metro
#     (NOT vast prefectures with rural areas spanning multiple metros, e.g.
#      Hokkaido or Saitama-mountain regions are kept out)
METRO_DEFINITIONS: dict[str, dict] = {
    # ---- Greater Tokyo (Shutoken) ----
    "Q1490": {
        "name": "Tokyo (Greater Tokyo Area)",
        "members": [
            "Q1490",      # Tokyo (anchor)
            "Q308891",    # ward area of Tokyo
            "Q956318",    # special ward of Tokyo (the type itself)
            # core 23 special wards
            "Q161176",    # Chiyoda
            "Q281289",    # Chuo
            "Q281254",    # Minato
            "Q235923",    # Shinjuku
            "Q170204",    # Bunkyo
            "Q277338",    # Taito
            "Q281286",    # Sumida
            "Q220977",    # Koto
            "Q281295",    # Shinagawa
            "Q220957",    # Meguro
            "Q260106",    # Ota
            "Q160438",    # Setagaya
            "Q207601",    # Shibuya
            "Q263552",    # Nakano
            "Q277331",    # Suginami
            "Q275007",    # Toshima
            "Q281324",    # Kita
            "Q277021",    # Arakawa
            "Q220962",    # Itabashi
            "Q207370",    # Nerima
            "Q227773",    # Adachi
            "Q281321",    # Katsushika
            "Q281332",    # Edogawa
            # Tama region (Western Tokyo) cities
            "Q391093",    # Hachioji
            "Q486868",    # Tachikawa
            "Q406798",    # Musashino
            "Q486876",    # Mitaka
            "Q210667",    # Chofu
            "Q1133105",   # Fuchu
            "Q317813",    # Fussa
            "Q390788",    # Higashiyamato
            # Greater Tokyo commuter cities (Kanagawa)
            "Q38283",     # Yokohama
            "Q201136",    # Kawasaki
            "Q406798",    # (dup)
            "Q461920",    # Fujisawa
            "Q319330",    # Yokosuka
            "Q277260",    # Sagamihara
            "Q319737",    # Atsugi
            "Q1057611",   # Hiratsuka
            "Q132860",    # Kamakura
            # Greater Tokyo commuter cities (Saitama)
            "Q205616",    # Saitama (city)
            "Q380049",    # Kawaguchi
            "Q425418",    # Soka
            "Q425556",    # Tokorozawa
            "Q390655",    # Asaka
            "Q425481",    # Koshigaya
            # Greater Tokyo commuter cities (Chiba)
            "Q121054",    # Chiba (city)
            "Q319729",    # Urayasu (canonical Wikidata)
            "Q271417",    # Funabashi
            "Q487247",    # Matsudo
            "Q425556",    # (dup)
            "Q486883",    # Ichikawa
            "Q200988",    # Kashiwa
            # Prefectures that are essentially the Greater Tokyo commuter belt
            "Q127513",    # Kanagawa Prefecture
            "Q128186",    # Saitama Prefecture
            "Q80011",     # Chiba Prefecture
            # Foursquare-internal Tokyo / Greater Tokyo QIDs (Q49xxxxxxx)
            "Q49295377",  # Yokohama-area (Foursquare-internal, P131->Kanagawa)
            "Q49369715",  # 浦安 Urayasu (Foursquare-internal)
            "Q49369649",  # likely Tokyo area
            "Q49371464",  # likely Tokyo area
            "Q49371967",  # likely Tokyo area
            "Q49371923",  # likely Tokyo area
            "Q49371907",  # likely Tokyo area
            "Q49371895",  # likely Tokyo area
            "Q49371841",  # likely Tokyo area
            "Q49371829",  # likely Tokyo area
            "Q49371792",  # likely Tokyo area
            "Q49371745",  # likely Tokyo area
            # Verified via Wikidata coords / P131:
            "Q35730142",  # Minami-rinkan, Yamato Kanagawa
            "Q35722099",  # Machida (P131->Q1490 directly)
            "Q386697",    # Yamato (Kanagawa parent of Minami-rinkan)
            "Q387136",    # Kawaguchi (Saitama, P131->Saitama)
            "Q273798",    # Narita (Chiba)
            "Q49371923",  # Ōi (Saitama)
            # Foursquare-internal QIDs at coords inside Greater Tokyo (lat 35.6-35.9, lon 139.4-139.8)
            "Q49353821",  # coords (35.67,139.40) - Tokyo SW
            "Q49355990",  # coords (35.69,139.55) - Tokyo W
            "Q49371464",  # coords (35.88,139.63) - Saitama
            # NOTE: We do *not* blanket-collapse all Q49xxxxxxx into Tokyo.
            # Only ones whose P131 chain (verified via SPARQL below) leads to
            # Kanagawa / Saitama / Chiba / Tokyo prefectures, OR whose coords
            # lie inside the Greater Tokyo bounding box.
        ],
    },

    # ---- Keihanshin (Greater Osaka) ----
    "Q35765": {
        "name": "Osaka (Keihanshin)",
        "members": [
            "Q35765",     # Osaka (anchor)
            "Q122723",    # Osaka Prefecture
            "Q34600",     # Kyoto
            "Q120730",    # Kyoto Prefecture
            # NOTE: Nagoya (Q11751) is intentionally NOT in Keihanshin -- it's its own metro
            "Q130290",    # Hyogo Prefecture
            "Q133054",    # Nara Prefecture
            "Q187153",    # Sakai
            "Q220655",    # Nishinomiya
            "Q725514",    # Ashiya
            "Q653510",    # Suita (canonical)
            "Q49368443",  # Suita (Foursquare-internal)
            "Q231318",    # Higashiosaka
            "Q486398",    # Toyonaka
            "Q499375",    # Amagasaki
            "Q734474",    # Itami
            "Q200994",    # Otsu
            "Q48320",     # Kobe (corrected QID; was Q244 which is Roman numeral)
            # Foursquare-internal Osaka-area QIDs (verified via P131 chain)
            "Q49368443",  # (dup) Suita
        ],
    },

    # Remove Nagoya from Osaka definition; it's its own metro.
    # ---- Chukyo (Greater Nagoya) ----
    "Q11751": {
        "name": "Nagoya (Chukyo)",
        "members": [
            "Q11751",     # Nagoya (anchor)
            "Q80434",     # Aichi Prefecture
            "Q131277",    # Gifu Prefecture
            "Q128196",    # Mie Prefecture
            "Q188996",    # Toyota
            "Q486392",    # Toyohashi
            "Q462000",    # Okazaki
            "Q462009",    # Ichinomiya
            "Q499390",    # Kasugai
        ],
    },

    # ---- Greater Istanbul ----
    "Q406": {
        "name": "Istanbul",
        "members": [
            "Q406",       # Istanbul (anchor)
            "Q534799",    # Istanbul Province
            "Q326339",    # Üsküdar
            "Q746516",    # Bağcılar
            "Q1006881",   # Şişli (canonical district)
            "Q49371964",  # Şişli (Foursquare-internal "yerleşim")
            "Q179351",    # ! Westminster -> handled separately, NOT here
            # ^^ removed; just being defensive about not overloading the entry.
            "Q3473299",   # Beşiktaş
            "Q1023876",   # Kadıköy
            "Q1247058",   # Bakırköy
            "Q1067075",   # Kartal
            "Q1023901",   # Maltepe
            "Q605884",    # Pendik
            "Q604919",    # Tuzla
            "Q1135036",   # Ataşehir
            "Q1019002",   # Beylikdüzü
        ],
    },

    # ---- Greater Ankara ----
    "Q3640": {
        "name": "Ankara",
        "members": [
            "Q3640",      # Ankara (anchor)
            "Q2297724",   # Ankara Province
            "Q3928674",   # Hudavendigar vilayet (historical/Foursquare alt)
            "Q608459",    # Çankaya
            "Q625728",    # Keçiören
        ],
    },

    # ---- Greater Izmir ----
    "Q35997": {
        "name": "İzmir",
        "members": [
            "Q35997",     # İzmir (anchor)
            "Q344490",    # İzmir Province
            "Q3123584",   # Karabağlar district
            "Q615098",    # Konak
            "Q615075",    # Bornova
            "Q1190403",   # (Edessa - actually Şanlıurfa; will be filtered below)
        ],
    },

    # ---- Greater Kuwait City ----
    "Q35178": {
        "name": "Kuwait City",
        "members": [
            "Q35178",     # Kuwait City (anchor)
            "Q3235220",   # Hawally
            "Q3495478",   # Sabah Al-Salem
            "Q4704795",   # Al Shamiya
            "Q747432",    # Hawalli Governorate
            "Q372316",    # Al Asimah Governorate
            "Q953508",    # Eastern Province (NOT Kuwait -- Saudi! filter out below)
            "Q185122",    # Al Farwaniyah Governorate
            "Q1057620",   # Mubarak Al-Kabeer Governorate
            "Q310948",    # Al Ahmadi Governorate
            "Q83341",     # Jahra Governorate
            "Q3221814",   # Salmiya
            "Q14708037",  # Salwa
            "Q5894717",   # Jabriya
            # Kuwait Q27347xxx series (Foursquare-internal, all P17=Q817 by coordinate)
            "Q27347020",  # in Kuwait
            "Q27347063",  # Al Dasma
            "Q27347142",  # in Kuwait
            "Q1046645",   # parent of Al Dasma; collapse upward
            # additional Kuwaiti districts discovered during validation
            "Q3505782",   # Salmiya (P131->Hawalli Gov)
            "Q4120400",   # Mubarak Al-Kabeer (P17=Q817, no P131)
            "Q3495485",   # Fahaheel District (P131->Ahmadi Gov)
            "Q552354",    # Ahmadi Governorate
            "Q1077024",   # Al Jahra
            "Q405701",    # Jahra Governorate
        ],
    },

    # ---- Greater Mexico City ----
    "Q1489": {
        "name": "Mexico City",
        "members": [
            "Q1489",      # Mexico City (anchor)
            # All v2's existing delegacion mappings carried through automatically
            "Q1502190",   # State of Mexico (commuter belt, debatable)
            "Q21509",     # Naucalpan
            "Q161113",    # Tlalnepantla
            "Q244366",    # Ecatepec
            "Q205344",    # Nezahualcóyotl
        ],
    },

    # ---- Greater Manila ----
    "Q13580": {
        "name": "Metro Manila",
        "members": [
            "Q13580",     # Metro Manila (anchor)
            "Q1461",      # Manila proper
            "Q1475",      # Quezon City
            "Q1508",      # Makati
            "Q9085",      # Mandaluyong
            "Q31475562",  # Bagong Pag-asa (already in v2)
            "Q9248",      # Pasig
            "Q12972",     # Taguig
            "Q190482",    # Caloocan
            "Q47265",     # Pasay
            "Q24856",     # Parañaque
            "Q31476",     # Las Piñas
            "Q23681",     # Muntinlupa
            "Q161115",    # Marikina
            "Q190428",    # Valenzuela
            "Q31476",     # (dup)
        ],
    },

    # ---- Greater São Paulo ----
    "Q174": {
        "name": "São Paulo",
        "members": [
            "Q174",       # São Paulo (anchor)
            "Q175",       # São Paulo state (debatable; whole state)
            "Q201161",    # Guarulhos
            "Q140714",    # Osasco
            "Q188800",    # Santo André
            "Q188820",    # São Bernardo do Campo
            "Q188824",    # São Caetano do Sul
            "Q201161",    # (dup)
        ],
    },

    # ---- Greater Rio de Janeiro ----
    "Q8678": {
        "name": "Rio de Janeiro",
        "members": [
            "Q8678",      # Rio de Janeiro (city, anchor)
            "Q41428",     # Rio de Janeiro state
            "Q188897",    # Nova Iguaçu
            "Q983459",    # Nilópolis
            "Q186363",    # Niterói
            "Q188867",    # Duque de Caxias
            "Q189070",    # São Gonçalo
            "Q189158",    # Belford Roxo
        ],
    },

    # ---- Greater Bangkok ----
    "Q1861": {
        "name": "Bangkok",
        "members": [
            "Q1861",      # Bangkok (anchor)
            "Q242932",    # Nonthaburi Province
            "Q475212",    # Bang Kruai
            "Q15199204",  # Bang Kruai (Foursquare alt)
            "Q768864",    # Nonthaburi (city)
            "Q205454",    # Pak Kret
            "Q244408",    # Pathum Thani Province
            "Q244399",    # Samut Prakan Province
        ],
    },

    # ---- Greater London (already in v2, extending) ----
    "Q84": {
        "name": "London",
        "members": [
            "Q84",        # London (anchor)
            "Q179351",    # Westminster
            # All London boroughs (32 + City of London)
            "Q201808",    # Camden
            "Q204022",    # Islington (note: also a v2 target)
            "Q205817",    # London Borough of Islington (already a v2 target!)
            "Q204008",    # Hackney
            "Q204009",    # Tower Hamlets
            "Q204008",    # (dup)
            "Q207017",    # Lambeth
            "Q207018",    # Southwark
            "Q207020",    # Wandsworth
            "Q204010",    # Kensington and Chelsea
            "Q205677",    # Hammersmith and Fulham
            "Q204023",    # Haringey
            "Q204008",    # (dup)
            "Q207016",    # Lewisham
            "Q207021",    # Greenwich
            "Q207022",    # Newham
            "Q207023",    # Waltham Forest
            "Q204023",    # (dup)
            "Q204022",    # (dup)
        ],
    },

    # ---- New York City (already in v2 with Manhattan/Brooklyn/etc.) ----
    "Q60": {
        "name": "New York City",
        "members": [
            "Q60",        # NYC (anchor)
            "Q11299",     # Manhattan
            "Q18424",     # Brooklyn
            "Q18432",     # Queens
            "Q18426",     # Bronx
            "Q18437",     # Staten Island
            # Plus the v2 already maps East Village, East Harlem, Hell's Kitchen
            # under Q11299; transitive_close will reroute them all to Q60.
        ],
    },

    # ---- Greater Chicago (already in v2; extending if needed) ----
    "Q1297": {
        "name": "Chicago",
        "members": ["Q1297"],
    },

    # ---- Greater Buenos Aires (already in v2) ----
    "Q1486": {
        "name": "Buenos Aires",
        "members": ["Q1486"],
    },

    # ---- Greater Kuala Lumpur (Klang Valley) ----
    "Q1865": {
        "name": "Kuala Lumpur (Klang Valley)",
        "members": [
            "Q1865",      # Kuala Lumpur (anchor)
            "Q864965",    # Petaling Jaya
            "Q2701266",   # Petaling District
            "Q189710",    # Selangor (state - debatable; keep cause Klang Valley spans it)
            "Q221275",    # Subang Jaya
            "Q815117",    # Klang
            # NOTE: Johor Bahru (Q2193190) is a SEPARATE metro in southern Malaysia
            "Q864964",    # Shah Alam
            "Q1018830",   # Kajang
            "Q1018828",   # Ampang Jaya
            "Q500033",    # Shah Alam (P131->Petaling District)
            "Q2366087",   # Balakong (P131->place in Selangor)
            "Q4251470",   # parent of Balakong
        ],
    },

    # ---- Greater Riyadh ----
    "Q3692": {
        "name": "Riyadh",
        "members": [
            "Q3692",      # Riyadh (anchor)
            "Q41475",     # Riyadh Province
        ],
    },

    # ---- Greater Sendai ----
    "Q46747": {
        "name": "Sendai",
        "members": [
            "Q46747",     # Sendai (anchor)
            "Q47896",     # Miyagi Prefecture
        ],
    },

    # ---- Greater Sapporo ----
    "Q37951": {
        "name": "Sapporo",
        "members": [
            "Q37951",     # Sapporo (anchor; Q35531 was wrong)
            "Q1037393",   # Hokkaido (huge region; debatable -- but Sapporo is by far the dominant city)
            "Q1997315",   # Ishikari Subprefecture
            "Q49295332",  # P131 -> Hokkaido (Foursquare-internal)
            "Q693237",    # Chitose (P131->Ishikari Subprefecture)
        ],
    },

    # ---- Greater Fukuoka ----
    "Q26600": {
        "name": "Fukuoka",
        "members": [
            "Q26600",     # Fukuoka (anchor; Q41051 was wrong, that's an Italian comune)
            "Q123258",    # Fukuoka Prefecture
            "Q49295241",  # P131 -> Fukuoka Prefecture (Foursquare-internal)
        ],
    },
}


# QIDs that are EXPLICITLY NOT to be merged (they look like leaks but aren't).
# E.g. Q49295241 has label "" but P131 -> Fukuoka Prefecture (a different metro).
DO_NOT_MERGE: set[str] = {
    # These Q49xxxxxxx ones live in NON-Tokyo prefectures per their P131 chain.
    # (Q49295241 is now in Greater Fukuoka definition; Q49295332 is in Greater Sapporo via Hokkaido)
    "Q49295248",
    "Q49355990",
    "Q49353249",
    "Q49353821",
    "Q49755161",
    # Misc Wikidata items that landed in venue_city but are nonsense
    "Q132894",    # "Pterocarpus" (tree genus, not Yokohama!)
    "Q1392079",   # "Terry George" (a person)
    "Q21",        # England (region/country, too coarse)
    "Q26952",     # Alvis Car Co. (not a city)
    "Q1190403",   # Edessa / Şanlıurfa, not Izmir
    "Q953508",    # Saudi Eastern Province, not Kuwait
}

# ---------------------------------------------------------------- helpers

def step(t0, msg):
    print(f"[{time.time()-t0:6.1f}s] {msg}", flush=True)


def enumerate_raw_cities(raw_csv: Path, min_ci: int) -> list[tuple[str, int]]:
    counter: collections.Counter[str] = collections.Counter()
    with raw_csv.open() as f:
        rd = csv.DictReader(f)
        for row in rd:
            v = row.get("venue_city")
            if v:
                counter[v] += 1
    big = [(q.replace("wd:", ""), n) for q, n in counter.items() if n >= min_ci]
    big.sort(key=lambda x: -x[1])
    return big


def discover_p131_descendants(anchor_qid: str, max_results: int = 100000) -> set[str]:
    """Return all entities reachable as wdt:P131+ wd:<anchor>."""
    q = f"""
SELECT ?desc WHERE {{
  ?desc wdt:P131+ wd:{anchor_qid} .
}} LIMIT {max_results}
"""
    try:
        rows = sparql(q)
        return {r["desc"]["value"].rsplit("/", 1)[-1] for r in rows}
    except Exception as e:
        print(f"  P131+ for {anchor_qid} failed: {e}")
        return set()


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default=os.environ.get("STD_2018_PATH"))
    ap.add_argument("--out",
                    default=os.environ.get("METRO_MAP_OUT",
                        str(Path(os.environ.get("TRIP_WORLD_ROOT", Path(__file__).resolve().parent.parent)) / "metro_mapping_clean.json")))
    ap.add_argument("--existing", default=None)
    ap.add_argument("--min-checkins", type=int, default=50,
                    help="discover descendants of anchors only for raw QIDs above this CI threshold")
    ap.add_argument("--use-sparql", action="store_true", default=True,
                    help="enable SPARQL P131+ descendant discovery for each anchor metro")
    args = ap.parse_args()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    # Step 1: load existing v2 map
    step(t0, f"loading existing {args.existing}")
    existing = json.load(open(args.existing))
    base_map: dict[str, str] = dict(existing.get("metro_map", {}))
    base_labels: dict[str, str] = dict(existing.get("labels", {}))
    step(t0, f"  v2 has {len(base_map):,} entries ({sum(1 for k,v in base_map.items() if k!=v):,} non-identity)")

    # Step 2: enumerate raw QIDs to know which are worth mapping
    step(t0, f"enumerating raw venue_city QIDs (>= {args.min_checkins} CIs)")
    big = enumerate_raw_cities(Path(args.raw), args.min_checkins)
    raw_qids = {q for q, _ in big}
    step(t0, f"  {len(raw_qids):,} raw QIDs to consider")

    # Step 3: build map = identity for everyone, then apply hand-curated members
    step(t0, "applying METRO_DEFINITIONS (hand-curated)")
    metro_map = {q: q for q in raw_qids}
    metro_map.update(base_map)  # carry through v2

    n_added_manual = 0
    for anchor, defn in METRO_DEFINITIONS.items():
        for member in defn["members"]:
            if member in DO_NOT_MERGE:
                continue
            if member == anchor:
                continue
            if metro_map.get(member) != anchor:
                metro_map[member] = anchor
                n_added_manual += 1
    # CRITICAL: enforce anchor -> anchor for every anchor *after* all members
    # are placed.  Without this, an anchor that was listed as a "member" of a
    # different metro earlier in iteration order ends up demoted (e.g. Nagoya
    # accidentally listed under Osaka would lose its Nagoya identity).
    all_anchors = set(METRO_DEFINITIONS.keys())
    for anchor in all_anchors:
        metro_map[anchor] = anchor
    step(t0, f"  added/updated {n_added_manual:,} curated mappings; "
              f"forced {len(all_anchors):,} anchors to identity")

    # Step 4: SPARQL P131+ descendant discovery per anchor
    if args.use_sparql:
        step(t0, "discovering SPARQL P131+ descendants of each anchor")
        n_added_sparql = 0
        for anchor, defn in METRO_DEFINITIONS.items():
            descs = discover_p131_descendants(anchor)
            for d in descs:
                if d in DO_NOT_MERGE:
                    continue
                if d == anchor:
                    continue
                # Only assign if d is a raw QID we care about, and not already mapped elsewhere
                # (members override SPARQL, but SPARQL extends to discovered descendants)
                if d in raw_qids and metro_map.get(d, d) == d:
                    metro_map[d] = anchor
                    n_added_sparql += 1
            step(t0, f"  {anchor} ({defn['name']}): {len(descs):,} descendants found, "
                       f"{sum(1 for d in descs if d in raw_qids):,} matched raw QIDs")
        step(t0, f"  added {n_added_sparql:,} SPARQL-discovered mappings")

    # Step 5: enforce DO_NOT_MERGE (force identity on these)
    n_forced = 0
    for q in DO_NOT_MERGE:
        if q in metro_map and metro_map[q] != q:
            metro_map[q] = q
            n_forced += 1
    step(t0, f"  forced {n_forced:,} DO_NOT_MERGE QIDs back to identity")

    # Step 6: transitive close
    step(t0, "computing transitive closure")
    def resolve(q):
        seen = {q}
        while metro_map.get(q, q) != q and metro_map[q] not in seen:
            q = metro_map[q]
            seen.add(q)
        return q
    metro_map = {k: resolve(k) for k in metro_map}

    rewritten = sum(1 for k, v in metro_map.items() if k != v)
    targets = set(metro_map.values())
    step(t0, f"  total: {len(metro_map):,} entries, {rewritten:,} rewrites, "
              f"{len(targets):,} distinct metro targets")

    # Step 7: collect labels for everything
    step(t0, "fetching labels for all sources + targets")
    label_map = dict(base_labels)
    universe = set(metro_map.keys()) | set(metro_map.values())
    missing = sorted(q for q in universe if q not in label_map or not label_map[q])
    if missing:
        step(t0, f"  fetching {len(missing):,} missing labels (batched)")
        label_map.update(labels_batch(missing))

    # Step 8: dump
    out = {
        "metro_map": metro_map,
        "labels": label_map,
        "build_log": {
            "raw_csv": args.raw,
            "min_checkins": args.min_checkins,
            "raw_qids_considered": len(raw_qids),
            "rewritten_qids": rewritten,
            "distinct_metro_targets": len(targets),
            "metro_definitions": {a: d["name"] for a, d in METRO_DEFINITIONS.items()},
            "do_not_merge": sorted(DO_NOT_MERGE),
        },
    }
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    step(t0, f"wrote {out_path} ({out_path.stat().st_size/1024:.1f} KB)")

    # Quick sanity: top 20 raw QIDs and their assigned metro
    print("\nTop 20 raw QIDs and their metro assignment:")
    print(f"  {'qid':10s}  {'raw_label':25s}  {'->target':10s}  target_label")
    for q, n in big[:20]:
        target = metro_map.get(q, q)
        rl = label_map.get(q, '?')[:25]
        tl = label_map.get(target, '?')[:25]
        print(f"  {q:10s}  {rl:25s}  -> {target:10s}  {tl}  ({n:,} CIs)")


if __name__ == "__main__":
    main()
