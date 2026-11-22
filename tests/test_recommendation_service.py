import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.catalog import places
from backend.main import app
from backend.models import Place
from backend.schemas.recommendations import Bounds, RecommendationRequest
from backend.services.recommendations import get_candidates, recommend


class RecommendationServiceTests(unittest.TestCase):
    def test_existing_order_explanations_and_version(self):
        request = RecommendationRequest(tripworld_region_id="demo-kyoto", visited_place_ids=["a1-mamas"])
        response = recommend(request)
        self.assertEqual(response.model_version, "stub-v1")
        self.assertEqual([p.id for p in response.results], [p.id for p in places if p.tripworld_region_id == "demo-kyoto"])
        self.assertEqual([p.rank for p in response.results], [1, 2, 3, 4])
        self.assertEqual(response.results[1].explanation,
                         "You visited Mama’s Fish House. Both places are in the dining category.")
        with TestClient(app) as client:
            self.assertEqual(client.post("/recommendations", json=request.model_dump()).json(), response.model_dump())

    def test_full_pool_is_available_before_display_limit(self):
        pool = [Place(id=f"p{i}", name=f"Place {i}", tripworld_region_id="demo-kyoto", lat=35, lng=135) for i in range(15)]
        with patch("backend.services.recommendations.places", [*places, *pool]):
            request = RecommendationRequest(tripworld_region_id="demo-kyoto", visited_place_ids=["a1-mamas"])
            self.assertEqual(len(get_candidates(request)), 19)
            self.assertEqual(len(recommend(request).results), 10)

    def test_scope_excludes_visited_and_applies_bounds(self):
        request = RecommendationRequest(tripworld_region_id="demo-kyoto", visited_place_ids=["demo-market"],
                                        bounds=Bounds(west=135.76, east=135.77, south=35, north=35.01))
        self.assertEqual([p.id for p in get_candidates(request)], ["a1-weekenders"])

    def test_unknown_ids_keep_existing_errors(self):
        with TestClient(app) as client:
            for region, visited, detail in [("missing", ["a1-mamas"], "Unknown destination"),
                                             ("demo-kyoto", ["missing"], "Unknown past place")]:
                response = client.post("/recommendations", json={"tripworld_region_id": region, "visited_place_ids": visited})
                self.assertEqual(response.status_code, 422)
                self.assertEqual(response.json()["detail"], detail)
