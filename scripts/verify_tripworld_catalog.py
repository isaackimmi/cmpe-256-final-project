"""Fresh-process acceptance checks for the destination-only SQLite export."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import platform
import sqlite3
import statistics
import sys
import time
import unicodedata

import duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.destination_catalog import Catalog, normalize


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',type=Path,required=True)
    parser.add_argument('--source-dir',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    report = {'passed':False,'scope':'destinations_only','checks':{},'examples':{},'model_coverage':'not_evaluated'}
    def check(name, condition, details=True):
        report['checks'][name] = details
        require(condition,name)
    try:
        source = args.source_dir.resolve()
        con = duckdb.connect()
        def parquet(name):
            return "read_parquet('"+str(source/name).replace("'","''")+"')"
        source_counts = dict(con.execute('SELECT r_o,count(*) FROM '+parquet('travel_behaviors.parquet')+' GROUP BY 1').fetchall())
        labels = {row[0]:row[1:] for row in con.execute('SELECT region_id,city_name,country_name FROM '+parquet('region_labels.parquet')).fetchall()}
        con.close()
        mapping = json.loads((source/'metro_mapping_clean.json').read_text())
        with Catalog(args.database) as catalog:
            db = catalog.connection
            all_destinations = [dict(row) for row in db.execute('SELECT * FROM destinations ORDER BY region_id')]
            exported = {row['region_id'] for row in all_destinations}
            source_ids = set(source_counts)
            differences = {'missing_from_export':sorted(source_ids-exported),'extra_in_export':sorted(exported-source_ids)}
            check('sqlite_integrity',db.execute('PRAGMA integrity_check').fetchone()[0]=='ok')
            check('foreign_keys',not db.execute('PRAGMA foreign_key_check').fetchall())
            check('destination_id_set_exact',not any(differences.values()),differences)
            check('one_row_per_destination',len(all_destinations)==len(exported)==len(source_ids),{'destinations':len(exported)})
            check('source_activity_counts_exact',all(row['source_trip_count']==source_counts[row['region_id']] for row in all_destinations))
            check('scope_is_destinations_only',db.execute("SELECT value FROM build_metadata WHERE key='scope'").fetchone()[0]=='destinations_only')
            check('model_coverage_not_claimed',db.execute("SELECT value FROM build_metadata WHERE key='model_coverage'").fetchone()[0].startswith('not_evaluated'))
            check('no_poi_tables',not db.execute("SELECT name FROM sqlite_master WHERE name IN ('places','place_names','place_search')").fetchall())
            check('no_candidate_counts',not {'candidate_count','coverage'}.intersection(all_destinations[0]))
            check('nonblank_display_labels',all(row['city_name'].strip() and row['canonical_metro_label'].strip() for row in all_destinations))
            # Independently require the canonical labels/countries to survive unchanged.
            for row in all_destinations:
                city,country = labels.get(row['region_id'],(None,None))
                city = ' '.join((city or '').split())
                is_raw = city.startswith('wd:Q') or (city.startswith('Q') and city[1:].isdigit())
                missing = not city or is_raw
                expected = row['region_id'] if missing else city
                require(row['city_name']==expected and row['label_missing']==int(missing),'Canonical label changed: '+row['region_id'])
                require(row['country_name']==(' '.join((country or '').split()) or None),'Country label changed: '+row['region_id'])
            check('published_labels_preserved',True)
            expected_names = {(row['region_id'],normalize(row['city_name'])) for row in all_destinations}
            for municipality,region in mapping['metro_map'].items():
                name = ' '.join((mapping['labels'].get(municipality) or '').split())
                is_raw = name.startswith('wd:Q') or (name.startswith('Q') and name[1:].isdigit())
                if region in exported and name and not is_raw and normalize(name):
                    expected_names.add((region,normalize(name)))
            actual_names = {tuple(row) for row in db.execute('SELECT region_id,normalized_name FROM destination_aliases')}
            check('published_alias_set_exact',actual_names==expected_names,{
                'missing':sorted(expected_names-actual_names),'extra':sorted(actual_names-expected_names),'names':len(actual_names)})
            check('alias_targets_exist',not db.execute('''SELECT a.region_id FROM destination_aliases a
                LEFT JOIN destinations d USING(region_id) WHERE d.region_id IS NULL''').fetchall())
            check('alias_normalization_consistent',all(row['normalized_name']==normalize(row['name']) and
                row['normalized_country']==normalize(row['country_name'] or '') for row in db.execute('SELECT * FROM destination_aliases')))
            aliases = [dict(row) for row in db.execute('SELECT * FROM destination_aliases ORDER BY id')]
            frequencies = Counter(row['normalized_name'] for row in aliases)
            checked = 0
            for row in aliases:
                if frequencies[row['normalized_name']]<=50 and len(row['name'])<=200:
                    matches = catalog.search_destinations(row['name'],50)
                    require(row['region_id'] in {match['region_id'] for match in matches},'Name not searchable: '+row['name'])
                    require(len(matches)==len({match['region_id'] for match in matches}),'Duplicate destination search results')
                    checked += 1
            check('published_names_searchable',checked==len(aliases),{'names_tested':checked,'total_names':len(aliases)})
            kyoto = catalog.search_destinations('Kyoto')
            check('kyoto_metro_scope',mapping['metro_map'].get('Q34600')=='Q35765' and bool(kyoto) and
                  kyoto[0]['region_id']=='Q35765' and kyoto[0]['matched_alias']=='Kyoto' and
                  kyoto[0]['canonical_metro_label']=='Osaka (Keihanshin)')
            report['examples']['Kyoto']=kyoto
            partial = catalog.search_destinations('Kyo')
            check('partial_name_search','Q35765' in {row['region_id'] for row in partial})
            report['examples']['Kyo']=partial
            accent_example = next(row for row in all_destinations if any(
                unicodedata.combining(ch) for ch in unicodedata.normalize('NFD',row['city_name'])) and len(row['city_name'])>4)
            folded = normalize(accent_example['city_name'])
            accent_results = catalog.search_destinations(folded,50)
            check('latin_accent_insensitive',accent_example['region_id'] in {row['region_id'] for row in accent_results})
            report['examples']['Accent-insensitive query']={'query':folded,'results':accent_results}
            names = Counter(row['normalized_name'] for row in all_destinations)
            ambiguous = next(row['normalized_name'] for row in all_destinations if 1<names[row['normalized_name']]<=10)
            ambiguous_expected = {row['region_id'] for row in all_destinations if row['normalized_name']==ambiguous}
            ambiguous_results = catalog.search_destinations(ambiguous,50)
            check('same_name_destinations_distinct',ambiguous_expected<={row['region_id'] for row in ambiguous_results})
            report['examples']['Same-name destinations']={'query':ambiguous,'results':ambiguous_results}
            context = next(row for row in all_destinations if row['normalized_name']==ambiguous and row['country_name'])
            contextual = catalog.search_destinations(context['city_name']+' '+context['country_name'],50)
            check('country_context_search',context['region_id'] in {row['region_id'] for row in contextual})
            sparse = min(all_destinations,key=lambda row:(row['source_trip_count'],row['region_id']))
            check('least_active_destination_retained',sparse['region_id'] in {row['region_id'] for row in catalog.search_destinations(sparse['city_name'],50)})
            report['examples']['Least-active source destination']=sparse
            report['missing_label_destinations']=[row['region_id'] for row in all_destinations if row['label_missing']]
            for query in ["'\"*():", 'x'*201, 'zzzzzzzzzzzznomatch']:
                check('empty_or_unmatched:'+repr(query[:20]),not catalog.search_destinations(query))
            for query in ["' OR 1=1 --", 'NEAR(Kyoto)', 'Kyoto OR London', '"Kyoto', 'a:b*']:
                require(len(catalog.search_destinations(query))<=10,'Unbounded or unsafe query')
            check('fts_punctuation_safe',True)
            check('limits_bounded',not catalog.search_destinations('a',0) and len(catalog.search_destinations('a',100000))<=100)
            check('empty_query_browses_catalog',bool(catalog.search_destinations('')))
            queries = ['Kyoto','Kyo','London','Paris','New York',folded,'zzzzzzzzzzzznomatch']
            for query in queries:
                catalog.search_destinations(query)
            durations = []
            for index in range(200):
                start=time.perf_counter_ns()
                catalog.search_destinations(queries[index%len(queries)])
                durations.append((time.perf_counter_ns()-start)/1_000_000)
            report['latency']={
                'queries':len(durations),'median_ms':round(statistics.median(durations),3),
                'p95_ms':round(sorted(durations)[189],3),'max_ms':round(max(durations),3),
                'query_cycle':queries,'conditions':'Warm SQLite/OS caches; seven warmup queries; one read-only connection; serial calls; excludes API/network time.',
                'python':sys.version.split()[0],'sqlite':sqlite3.sqlite_version,'platform':platform.platform(),
            }
            report['database_size_bytes']=args.database.stat().st_size
            report['passed']=True
    finally:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({key:report[key] for key in ['scope','passed','latency']},indent=2))
    print('Acceptance checks:',len(report['checks']))


if __name__=='__main__':
    main()
