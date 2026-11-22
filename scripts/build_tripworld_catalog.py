"""Build the destination-input catalog only; POI/model preprocessing is deferred."""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request

import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.destination_catalog import normalize

REVISION = "254f142dfef42104783754019f7b7f4cfbf8d9a8"
DATASET = "CRUISEResearchGroup/TripWorld"
BASE = f"https://huggingface.co/datasets/{DATASET}/resolve/{REVISION}/"
SOURCE_FILES = ["travel_behaviors.parquet", "region_labels.parquet", "metro_mapping_clean.json"]


def clean(value):
    return " ".join(str(value).split()) if value is not None else ""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def download(url: str, path: Path, expected: str | None = None) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or (expected and sha256(path) != expected):
        tmp = path.with_name(path.name + ".download")
        with urllib.request.urlopen(url, timeout=120) as response, tmp.open("wb") as out:
            shutil.copyfileobj(response, out)
        if expected and sha256(tmp) != expected:
            tmp.unlink()
            raise ValueError(f"Checksum mismatch: {url}")
        os.replace(tmp, path)
    return {"path": str(path), "size_bytes": path.stat().st_size, "sha256": sha256(path)}


def fetch_sources(source_dir: Path, provenance: Path) -> dict:
    manifest_path = source_dir / "MANIFEST.json"
    download(BASE + "MANIFEST.json", manifest_path)
    upstream = json.loads(manifest_path.read_text())
    entries = {item["path"]: item for item in upstream["files"]}
    with urllib.request.urlopen(f"https://huggingface.co/api/datasets/{DATASET}/tree/{REVISION}?recursive=true", timeout=120) as response:
        git_entries = {item['path']: item for item in json.load(response) if item['type'] == 'file'}
    content = manifest_path.read_bytes()
    if hashlib.sha1(b'blob ' + str(len(content)).encode() + b'\0' + content).hexdigest() != git_entries['MANIFEST.json']['oid']:
        raise ValueError('Upstream manifest does not match its pinned Git blob')
    provenance.mkdir(parents=True, exist_ok=True)
    shutil.copy2(manifest_path, provenance / "MANIFEST.json")
    paths = SOURCE_FILES + [name for name in entries if name == "README.md" or name.startswith("_scripts/")]
    def fetch(name):
        target = source_dir / name if name in SOURCE_FILES else provenance / name
        info = download(BASE + name, target, entries[name]["sha256"] if name in SOURCE_FILES else None)
        info['path'] = name
        if name not in SOURCE_FILES:
            # The upstream manifest predates edits to the README/provenance scripts.
            # Verify those against their immutable Git blob instead of stale hashes.
            content = target.read_bytes()
            git_oid = hashlib.sha1(b'blob ' + str(len(content)).encode() + b'\0' + content).hexdigest()
            if git_oid != git_entries[name]['oid']:
                raise ValueError(f'Git blob mismatch: {name}')
            info['verified_git_blob'] = git_oid
            info['upstream_manifest_sha256'] = entries[name]['sha256']
            info['upstream_manifest_matches'] = info['sha256'] == entries[name]['sha256']
        return name, info
    with ThreadPoolExecutor(max_workers=4) as pool:
        result = dict(pool.map(fetch, paths))
    return result


def rows(con, sql, parameters=None):
    cursor = con.execute(sql, parameters or [])
    columns = [item[0] for item in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def profile_sources(source_dir):
    con = duckdb.connect()
    con.execute("SET memory_limit='512MB'")
    con.execute("SET threads=2")
    con.execute("SET temp_directory=?", [str(source_dir/'duckdb_tmp')])
    for table, filename in [('travel', 'travel_behaviors.parquet'), ('regions_raw', 'region_labels.parquet')]:
        # Project only the one travel column and three label columns needed here.
        columns = 'r_o' if table == 'travel' else 'region_id,city_name,country_name'
        escaped = str(source_dir/filename).replace("'", "''")
        con.execute(f"CREATE VIEW {table} AS SELECT {columns} FROM read_parquet('{escaped}')")
    con.execute('CREATE TABLE regions AS SELECT DISTINCT * FROM regions_raw')
    profile = {
        'source_trip_records': con.execute('SELECT count(*) FROM travel').fetchone()[0],
        'invalid_destination_records': con.execute("SELECT count(*) FROM travel WHERE r_o IS NULL OR trim(r_o)=''").fetchone()[0],
        'source_destination_count': con.execute('SELECT count(DISTINCT r_o) FROM travel').fetchone()[0],
        'label_source_rows': con.execute('SELECT count(*) FROM regions_raw').fetchone()[0],
        'distinct_label_records': con.execute('SELECT count(*) FROM regions').fetchone()[0],
        'label_conflicts': rows(con, 'SELECT region_id,count(*) records FROM regions GROUP BY 1 HAVING count(*)>1 ORDER BY 1'),
        'destinations_missing_label_rows': rows(con, '''SELECT DISTINCT r_o FROM travel
            EXCEPT SELECT region_id FROM regions ORDER BY 1'''),
    }
    profile['exact_label_duplicates_removed'] = profile['label_source_rows']-profile['distinct_label_records']
    destinations = rows(con, '''SELECT d.region_id,d.source_trip_count,r.city_name,r.country_name
        FROM (SELECT r_o region_id,count(*) source_trip_count FROM travel GROUP BY 1) d
        LEFT JOIN regions r USING(region_id) ORDER BY d.region_id''')
    con.close()
    return destinations, profile


SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE destinations (
 region_id TEXT PRIMARY KEY NOT NULL, city_name TEXT NOT NULL,
 normalized_name TEXT NOT NULL, country_name TEXT, canonical_metro_label TEXT NOT NULL,
 label_missing INTEGER NOT NULL CHECK(label_missing IN (0,1)),
 source_trip_count INTEGER NOT NULL CHECK(source_trip_count>0)
);
CREATE TABLE destination_aliases (
 id INTEGER PRIMARY KEY, region_id TEXT NOT NULL REFERENCES destinations(region_id),
 name TEXT NOT NULL, normalized_name TEXT NOT NULL, country_name TEXT,
 normalized_country TEXT NOT NULL, is_canonical INTEGER NOT NULL CHECK(is_canonical IN (0,1)),
 municipality_id TEXT, UNIQUE(region_id,normalized_name)
);
CREATE INDEX destination_aliases_exact ON destination_aliases(normalized_name);
CREATE VIRTUAL TABLE destination_search USING fts5(normalized_name,normalized_country,
 content='destination_aliases',content_rowid='id',tokenize='unicode61 remove_diacritics 0',prefix='2 3 4');
CREATE TABLE build_metadata (key TEXT PRIMARY KEY,value TEXT NOT NULL);
"""


def raw_id_label(name):
    return bool(re.fullmatch(r'(?:wd:)?Q\d+', name))


def build_database(destinations, mapping, output):
    counts = Counter()
    missing = []
    db = sqlite3.connect(output)
    try:
        db.executescript(SCHEMA)
        countries = {}
        for destination in sorted(destinations, key=lambda row: row['region_id']):
            region_id = destination['region_id']
            name = clean(destination['city_name'])
            label_missing = not name or raw_id_label(name)
            name = region_id if label_missing else name
            country = clean(destination['country_name']) or None
            countries[region_id] = country
            scope = clean(mapping.get('build_log', {}).get('metro_definitions', {}).get(region_id)) or name
            db.execute('INSERT INTO destinations VALUES (?,?,?,?,?,?,?)',
                       (region_id,name,normalize(name),country,scope,int(label_missing),destination['source_trip_count']))
            db.execute('''INSERT INTO destination_aliases(region_id,name,normalized_name,country_name,
                normalized_country,is_canonical,municipality_id) VALUES (?,?,?,?,?,1,?)''',
                       (region_id,name,normalize(name),country,normalize(country or ''),region_id))
            counts['destinations'] += 1
            counts['canonical_names'] += 1
            if label_missing:
                missing.append(region_id)
        for municipality, region_id in sorted(mapping['metro_map'].items()):
            if region_id not in countries:
                counts['mapping_entries_outside_destinations'] += 1
                continue
            name = clean(mapping['labels'].get(municipality))
            if not name or raw_id_label(name) or not normalize(name):
                counts['mapping_entries_without_searchable_label'] += 1
                continue
            before = db.total_changes
            db.execute('''INSERT OR IGNORE INTO destination_aliases(region_id,name,normalized_name,
                country_name,normalized_country,is_canonical,municipality_id) VALUES (?,?,?,?,?,0,?)''',
                       (region_id,name,normalize(name),countries[region_id],normalize(countries[region_id] or ''),municipality))
            counts['mapping_aliases_added' if db.total_changes>before else 'mapping_names_deduplicated'] += 1
        db.execute("INSERT INTO destination_search(destination_search) VALUES ('rebuild')")
        # Compare the FTS index to its external-content table, not just row counts.
        db.execute("INSERT INTO destination_search(destination_search,rank) VALUES ('integrity-check',1)")
        db.executemany('INSERT INTO build_metadata VALUES (?,?)', [
            ('source_revision',REVISION), ('scope','destinations_only'), ('schema_version','2'),
            ('model_coverage','not_evaluated; awaiting cleaned POI/model IDs'),
            ('name_policy','Preserve published names and scripts; no language or ASCII filter'),
        ])
        db.commit()
        db.execute('ANALYZE')
        db.execute('VACUUM')
    finally:
        db.close()
    return {'counts':dict(counts),'destinations_with_missing_labels':missing,
            'scope':'destinations_only','model_coverage':'not_evaluated'}


def logical_checksum(database):
    digest = hashlib.sha256()
    with sqlite3.connect(database) as db:
        for table, order in [('destinations','region_id'),('destination_aliases','region_id,normalized_name'),('build_metadata','key')]:
            columns = [row[1] for row in db.execute(f'PRAGMA table_info({table})') if row[1]!='id']
            digest.update(table.encode())
            for row in db.execute(f"SELECT {','.join(columns)} FROM {table} ORDER BY {order}"):
                digest.update((json.dumps(row,ensure_ascii=False,separators=(',',':'))+'\n').encode())
    return digest.hexdigest()


def publish_validated(temporary, output, validation_command):
    try:
        subprocess.run(validation_command, check=True)
        os.replace(temporary, output)
    finally:
        if temporary.exists():
            temporary.unlink()


def write_summary(report_dir, manifest, audit, validation):
    lines = [
        '# TripWorld destination-input catalog', '',
        'Scope: city/destination autocomplete only. Past-visit POIs, recommendation candidates, '
        'Google-category filtering, and model coverage are deferred until the cleaned POI IDs are available.', '',
        f"- Pinned source revision: `{REVISION}`.",
        f"- Destinations: {manifest['counts']['destinations']:,}; exactly the source's distinct `r_o` set.",
        f"- Additional metro aliases: {manifest['counts'].get('mapping_aliases_added',0):,}.",
        f"- Destinations with missing/raw-ID labels: {len(audit['destinations_with_missing_labels'])} (retained).",
        f"- SQLite: {manifest['database_size_bytes']:,} bytes.",
        f"- SHA-256: `{manifest['database_sha256']}`.",
        f"- Logical SHA-256: `{manifest['logical_sha256']}`.",
        f"- Fresh-process checks: {len(validation['checks'])} passed.",
        f"- Rebuild logical match: {audit.get('same_as_previous_build','not yet run')}.", '',
        '## Real search output', '',
    ]
    for name, results in validation['examples'].items():
        lines += [f'### {name}', '', '```json',json.dumps(results,ensure_ascii=False,indent=2),'```','']
    lines += ['## Latency', '', '```json',json.dumps(validation['latency'],indent=2),'```','',
        'Names retain their original scripts. Search uses published names and aliases; it does not invent '
        'translations, local-language equivalents, typo corrections, or arbitrary substring matches. '
        'FTS5 provides token prefixes; Japanese/Thai word segmentation is not claimed.', '',
        '`source_trip_count` counts source travel records, not model-compatible POIs or available recommendations. '
        'A selectable destination does not guarantee that the future model can recommend venues there.', '',
        'The notebook was executed locally with a Python kernel; Google-hosted Colab UI execution and deployment were not performed.', '',
        'The upstream README hash differs from its upstream manifest; provenance is verified using the pinned Git blob. '
        'All three catalog source files must match the upstream SHA-256 manifest.', '',
        'POI search and recommendation model integration are separate from this destination export.']
    (report_dir/'tripworld_catalog_summary.md').write_text('\n'.join(lines)+'\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-dir',type=Path,default=ROOT/'data'/'tripworld')
    parser.add_argument('--output',type=Path,default=ROOT/'backend'/'artifacts'/'tripworld_destinations.sqlite')
    parser.add_argument('--report-dir',type=Path,default=ROOT/'reports')
    args = parser.parse_args()
    source_dir,output,report_dir = args.source_dir.resolve(),args.output.resolve(),args.report_dir.resolve()
    output.parent.mkdir(parents=True,exist_ok=True)
    report_dir.mkdir(parents=True,exist_ok=True)
    started = time.perf_counter()
    print('Checking three pinned destination sources; no POIs, metadata, or reviews are read.',flush=True)
    source_files = fetch_sources(source_dir,output.parent/'tripworld_provenance')
    destinations, profile = profile_sources(source_dir)
    (report_dir/'tripworld_catalog_profile.json').write_text(json.dumps(profile,ensure_ascii=False,indent=2)+'\n')
    if profile['invalid_destination_records'] or profile['label_conflicts']:
        raise ValueError('Invalid destination IDs or conflicting labels: see source profile')
    mapping = json.loads((source_dir/'metro_mapping_clean.json').read_text())
    fd, temporary_name = tempfile.mkstemp(prefix=output.name+'.',suffix='.building',dir=output.parent)
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        audit = build_database(destinations,mapping,temporary)
        audit.update(source_revision=REVISION,profile=profile)
        verification = report_dir/'tripworld_catalog_validation.json'
        command = [sys.executable,str(ROOT/'scripts/verify_tripworld_catalog.py'),
                   '--database',str(temporary),'--source-dir',str(source_dir),'--output',str(verification)]
        logical = logical_checksum(temporary)
        manifest_path = report_dir/'tripworld_catalog_manifest.json'
        if manifest_path.exists():
            previous = json.loads(manifest_path.read_text())
            if previous.get('scope') == 'destinations_only':
                audit['same_as_previous_build'] = logical==previous.get('logical_sha256')
                audit['previous_logical_checksum'] = previous.get('logical_sha256')
        manifest = {
            'scope':'destinations_only','schema_version':2,'dataset':DATASET,'source_revision':REVISION,
            'database':str(output.relative_to(ROOT)) if output.is_relative_to(ROOT) else str(output),
            'database_size_bytes':temporary.stat().st_size,'database_sha256':sha256(temporary),
            'logical_sha256':logical,'counts':audit['counts'],'model_coverage':'not_evaluated',
            'source_files':source_files,'built_at_utc':datetime.now(timezone.utc).isoformat(),
            'dependencies':{'duckdb':importlib.metadata.version('duckdb')},
            'python':sys.version,'sqlite':sqlite3.sqlite_version,
            'implementation_sha256':{str(path.relative_to(ROOT)):sha256(path) for path in [
                Path(__file__),ROOT/'scripts/verify_tripworld_catalog.py',ROOT/'backend/destination_catalog.py',ROOT/'scripts/requirements-catalog.txt']},
        }
        publish_validated(temporary,output,command)
        validation = json.loads(verification.read_text())
        manifest.update(validation_passed=True,build_seconds=round(time.perf_counter()-started,2))
        manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
        audit['validation'] = validation
        (report_dir/'tripworld_catalog_audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2)+'\n')
        write_summary(report_dir,manifest,audit,validation)
        print(json.dumps({key:manifest[key] for key in ['scope','database','database_size_bytes','counts','logical_sha256','build_seconds']},indent=2))
    finally:
        if temporary.exists():
            temporary.unlink()


if __name__=='__main__':
    main()
