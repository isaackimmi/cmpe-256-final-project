"""Destination-only search behavior, Unicode preservation, and atomic publishing."""
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from backend.destination_catalog import Catalog, normalize
from scripts.build_tripworld_catalog import build_database, publish_validated


class DestinationCatalogTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)/'destinations.sqlite'
        destinations = [
            {'region_id':region,'city_name':city,'country_name':country,'source_trip_count':trips}
            for region,city,country,trips in [
                ('A','Springfield','United States',2),('B','Springfield','Canada',1),
                ('Q35765','Osaka','Japan',10),('D','Łódź','Poland',3),
                ('E','東京都','Japan',4),('F','กรุงเทพมหานคร','Thailand',5),
                ('Q9999',None,None,1),
            ]
        ]
        mapping = {'metro_map':{'Q34600':'Q35765','old':'A','outside':'X'},
                   'labels':{'Q34600':'Kyoto','old':'Old Springfield','outside':'Outside City'},
                   'build_log':{'metro_definitions':{'Q35765':'Osaka (Keihanshin)'}}}
        build_database(destinations,mapping,self.path)
        self.catalog = Catalog(self.path)

    def tearDown(self):
        self.catalog.close()
        self.temp.cleanup()

    def test_kyoto_alias_reports_canonical_metro(self):
        result = self.catalog.search_destinations('Kyo')[0]
        self.assertEqual((result['region_id'],result['matched_alias'],result['canonical_metro_label']),
                         ('Q35765','Kyoto','Osaka (Keihanshin)'))

    def test_same_name_cities_and_country_context(self):
        result = self.catalog.search_destinations('Springfield')
        self.assertEqual({row['region_id'] for row in result},{'A','B'})
        self.assertEqual(self.catalog.search_destinations('Springfield Canada')[0]['region_id'],'B')
        self.assertEqual(self.catalog.search_destinations('Old Springfield')[0]['region_id'],'A')

    def test_exact_canonical_before_alias_and_no_duplicates(self):
        with sqlite3.connect(self.path) as db:
            db.execute("INSERT INTO destination_aliases(region_id,name,normalized_name,country_name,normalized_country,is_canonical) VALUES ('Q35765','Springfield','springfield','Japan','japan',0)")
            db.execute("INSERT INTO destination_search(destination_search) VALUES ('rebuild')")
        result = self.catalog.search_destinations('Springfield')
        self.assertEqual({row['region_id'] for row in result[:2]},{'A','B'})
        self.assertEqual(result[2]['region_id'],'Q35765')

    def test_latin_accents_and_non_decomposing_letters(self):
        self.assertEqual(normalize('Łódź'),'lodz')
        self.assertEqual(self.catalog.search_destinations('lodz')[0]['city_name'],'Łódź')
        self.assertEqual(normalize('São Paulo'),'sao paulo')
        self.assertEqual(normalize('Torbalı'),'torbali')

    def test_unicode_is_preserved_without_translating(self):
        self.assertEqual(self.catalog.search_destinations('東')[0]['city_name'],'東京都')
        self.assertEqual(self.catalog.search_destinations('กรุงเทพมหานคร')[0]['region_id'],'F')
        self.assertEqual(normalize('กรุงเทพมหานคร'),'กรุงเทพมหานคร')
        self.assertEqual(self.catalog.search_destinations('Tokyo'),[])

    def test_missing_label_and_low_activity_retained(self):
        row = self.catalog.search_destinations('Q9999')[0]
        self.assertTrue(row['label_missing'])
        self.assertEqual(row['source_trip_count'],1)
        self.assertNotIn('candidate_count',row)
        self.assertNotIn('coverage',row)

    def test_query_safety_and_limits(self):
        for query in ["'\"*():", 'a'*201, "' OR 1=1 --", 'NEAR(Springfield)', 'Springfield OR Osaka']:
            self.assertEqual(self.catalog.search_destinations(query),[])
        self.assertEqual(self.catalog.search_destinations('Springfield',0),[])
        self.assertEqual(len(self.catalog.search_destinations('Springfield',1)),1)
        with self.assertRaises(ValueError):
            self.catalog.search_destinations('Kyoto','10')

    def test_open_is_read_only_and_no_poi_scope(self):
        with self.assertRaises(sqlite3.OperationalError):
            self.catalog.connection.execute('DELETE FROM destinations')
        self.assertFalse(hasattr(self.catalog,'search_places'))
        self.assertFalse(hasattr(self.catalog,'get_destination_candidates'))


class PublicationTests(unittest.TestCase):
    def test_validation_failure_preserves_existing_database(self):
        with tempfile.TemporaryDirectory() as directory:
            final = Path(directory)/'destinations.sqlite'
            temporary = Path(directory)/'new.building'
            final.write_bytes(b'previous validated artifact')
            temporary.write_bytes(b'unvalidated artifact')
            with patch('scripts.build_tripworld_catalog.subprocess.run',
                       side_effect=subprocess.CalledProcessError(1,['verify'])):
                with self.assertRaises(subprocess.CalledProcessError):
                    publish_validated(temporary,final,['verify'])
            self.assertEqual(final.read_bytes(),b'previous validated artifact')
            self.assertFalse(temporary.exists())


if __name__=='__main__':
    unittest.main()
