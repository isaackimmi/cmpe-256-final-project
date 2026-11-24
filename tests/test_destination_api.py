"""Real destination catalog through the same API contract as the frontend."""
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.destination_catalog import DEFAULT_DATABASE
from backend.main import app


class DestinationAPITests(unittest.TestCase):
    def setUp(self):
        self.client = self.enterContext(TestClient(app))

    def test_browse_all_real_destinations_with_existing_pagination(self):
        items = []
        offset = 0
        while True:
            response = self.client.get('/destinations/search', params={'limit':100,'offset':offset})
            self.assertEqual(response.status_code,200)
            page = response.json()
            self.assertLessEqual(len(page['items']),100)
            items.extend(page['items'])
            if page['next_offset'] is None:
                break
            self.assertEqual(page['next_offset'],offset+100)
            offset = page['next_offset']
        with sqlite3.connect(DEFAULT_DATABASE) as db:
            expected = {row[0] for row in db.execute('SELECT region_id FROM destinations')}
        self.assertEqual(len(items),1165)
        self.assertEqual({row['id'] for row in items},expected)
        self.assertEqual(len(items),len(expected))
        self.assertTrue(all(row['id'].startswith('Q') for row in items))
        self.assertEqual(self.client.get('/destinations/search',params={'offset':len(items)}).json(),
                         {'items':[],'next_offset':None})

    def test_kyoto_alias_exposes_real_id_and_metro_scope(self):
        response = self.client.get('/destinations/search',params={'q':'Kyoto'})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['items'][0],{
            'id':'Q35765','name':'Kyoto','country':'Japan','canonical_name':'Osaka',
            'canonical_metro_label':'Osaka (Keihanshin)','matched_alias':'Kyoto',
        })
        self.assertIsNone(response.json()['next_offset'])
        self.assertEqual(self.client.get('/destinations/search',params={'q':'Kyo'}).json()['items'][0]['id'],'Q35765')

    def test_canonical_label_country_and_accents(self):
        london = self.client.get('/destinations/search',params={'q':'London United Kingdom'}).json()['items']
        self.assertEqual(london[0]['id'],'Q84')
        self.assertEqual(london[0]['name'],'London')
        self.assertIsNone(london[0]['matched_alias'])
        folded = self.client.get('/destinations/search',params={'q':'Sao Paulo'}).json()['items']
        self.assertIn('Q174',{row['id'] for row in folded})

    def test_filtered_pagination_is_stable_and_deduplicated(self):
        params = {'q':'san','limit':100}
        response = self.client.get('/destinations/search',params=params).json()
        expected = response['items']
        self.assertGreater(len(expected),3)
        self.assertIsNone(response['next_offset'])
        actual = []
        offset = 0
        while True:
            page = self.client.get('/destinations/search',params={'q':'san','limit':3,'offset':offset}).json()
            actual.extend(page['items'])
            if page['next_offset'] is None:
                break
            offset = page['next_offset']
        self.assertEqual(actual,expected)
        self.assertEqual(len({row['id'] for row in actual}),len(actual))

    def test_queries_and_pagination_boundaries(self):
        for query in ['***', "' OR 1=1 --", 'zzzzzzzzzznomatch', 'NEAR(Kyoto)']:
            with self.subTest(query=query):
                self.assertEqual(self.client.get('/destinations/search',params={'q':query}).json(),
                                 {'items':[],'next_offset':None})
        for params in [{'q':'x'*201},{'offset':-1},{'limit':0},{'limit':101}]:
            self.assertEqual(self.client.get('/destinations/search',params=params).status_code,422)
        self.assertEqual(self.client.get('/destinations/search',params={'offset':10**100}).json(),
                         {'items':[],'next_offset':None})
        self.assertEqual(self.client.get('/destinations/search',params={'q':'  '}).json(),
                         self.client.get('/destinations/search').json())

    def test_real_destination_validation_keeps_recommendations_explicitly_sample_only(self):
        body = {'tripworld_region_id':'Q35765','visited_place_ids':['a1-mamas','a1-golf']}
        response = self.client.post('/recommendations',json=body)
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['model_version'],'stub-v1')
        self.assertEqual(len(response.json()['results']),4)
        self.assertTrue(all(row['tripworld_region_id']=='Q35765' for row in response.json()['results']))
        self.assertTrue(all(row['explanation'].startswith('Sample result:') for row in response.json()['results']))
        for region in ['demo-kyoto','Q-does-not-exist',"Q35765' OR 1=1 --"]:
            self.assertEqual(self.client.post('/recommendations',json=dict(body,tripworld_region_id=region)).status_code,422)
        # Boston is a verified source destination; absence of a model is not an unknown ID
        # or a claim that Boston has no places of interest.
        unavailable = self.client.post('/recommendations',json=dict(body,tripworld_region_id='Q100'))
        self.assertEqual(unavailable.status_code,503)
        self.assertIn('not available',unavailable.json()['detail'])
        self.assertEqual(self.client.post('/recommendations',json=dict(body,visited_place_ids=['invalid'])).status_code,422)


class DestinationStartupTests(unittest.TestCase):
    def test_missing_artifact_fails_startup_with_clear_path(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory)/'missing.sqlite')
            with patch.dict(os.environ,{'TRIPWORLD_DESTINATIONS_DB':path}):
                with self.assertRaisesRegex(RuntimeError,'Cannot open destination catalog'):
                    with TestClient(app):
                        pass
            self.assertFalse(Path(path).exists())

    def test_wrong_artifact_fails_startup(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory)/'wrong.sqlite')
            with sqlite3.connect(path) as db:
                db.execute('CREATE TABLE build_metadata(key TEXT,value TEXT)')
                db.execute("INSERT INTO build_metadata VALUES ('scope','places')")
            with patch.dict(os.environ,{'TRIPWORLD_DESTINATIONS_DB':path}):
                with self.assertRaisesRegex(RuntimeError,'Unsupported destination catalog'):
                    with TestClient(app):
                        pass


if __name__=='__main__':
    unittest.main()
