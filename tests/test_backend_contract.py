import unittest

from fastapi.testclient import TestClient

from backend.main import app


class BackendContractTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def test_last_page_has_no_next_offset(self):
        for path in ("/places/search", "/destinations/search"):
            with self.subTest(path=path):
                full = self.client.get(path, params={"limit": 100}).json()["items"]
                self.assertGreater(len(full), 1)
                last = self.client.get(path, params={"limit": 1, "offset": len(full) - 1})
                self.assertEqual(last.status_code, 200)
                self.assertEqual(last.json(), {"items": full[-1:], "next_offset": None})
                beyond = self.client.get(path, params={"limit": 1, "offset": len(full)})
                self.assertEqual(beyond.json(), {"items": [], "next_offset": None})

    def test_invalid_longitudes_return_structured_validation_errors(self):
        for longitude, expected_input in (("181", 181), ("1e999", "inf")):
            with self.subTest(longitude=longitude):
                # Send numeric literals so the overflowing exponent reaches the JSON parser.
                payload = (
                    '{"tripworld_region_id":"demo-kyoto","visited_place_ids":["demo-park"],'
                    '"bounds":{"south":30,"north":39,"east":140,"west":' + longitude + '}}'
                )
                response = self.client.post(
                    "/recommendations", content=payload, headers={"Content-Type": "application/json"}
                )
                self.assertEqual(response.status_code, 422)
                error = response.json()["detail"][0]
                self.assertEqual(error["loc"], ["body", "bounds", "west"])
                self.assertEqual(error["type"], "less_than_equal")
                self.assertEqual(error["input"], expected_input)
