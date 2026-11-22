from unittest import TestCase
from unittest.mock import patch

from fastapi.testclient import TestClient
from backend.main import app


class FeedbackTests(TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.payload = dict(tripworld_region_id="demo-kyoto", visited_place_ids=["a1-mamas"],
                            current_place_ids=["a1-kyocera", "demo-market", "demo-garden", "a1-weekenders"],
                            feedback=[dict(place_id="demo-market", vote="like"),
                                      dict(place_id="a1-kyocera", vote="dislike")])

    def post(self):
        return self.client.post("/agent/feedback", json=self.payload)

    @patch("backend.services.agent.interpret", return_value={"Dining": 1, "Art & culture": -1})
    def test_preserve_like_and_remove_dislike(self, interpret):
        data = self.post().json()
        self.assertEqual(data["results"][1]["id"], "demo-market")
        self.assertEqual(data["removed_place_ids"], ["a1-kyocera"])
        self.assertEqual(len(data["results"]), 3)
        interpret.assert_awaited_once()

    def test_foreign_vote_rejected(self):
        self.payload["feedback"][0]["place_id"] = "a1-mamas"
        self.assertEqual(self.post().status_code, 422)

    @patch.dict("os.environ", {"GEMINI_API_KEY": ""})
    def test_unavailable_and_clear(self):
        self.assertEqual(self.post().status_code, 503)
        self.payload["feedback"] = []
        self.assertEqual(len(self.post().json()["results"]), 4)
