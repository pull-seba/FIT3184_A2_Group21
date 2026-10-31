import csv
import shutil
import tempfile
import unittest
from pathlib import Path

import bakeoff

FIELDS = ["filename", "species", "true_count", "condition", "verified"]


def label(name, conf, boxes=()):
    return {
        "Name": name,
        "Confidence": conf,
        "Instances": [{"Confidence": c} for c in boxes],
        "Parents": [],
        "Aliases": [],
    }


class FakeRekognition:
    def __init__(self, responses):
        self.responses = responses  # list, returned in call order
        self.calls = 0

    def detect_labels(self, **kwargs):
        assert "Bytes" in kwargs["Image"]
        self.calls += 1
        return {"Labels": self.responses[self.calls - 1]}


class BakeoffTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir)
        rows = [
            ("fox/fox_001.jpg", "fox", "2", "night", "ok"),
            ("neg_hare/neg_hare_001.jpg", "none", "0", "clear", "ok"),
            ("fox/fox_002.jpg", "fox", "1", "clear", "reject"),
        ]
        with (self.dir / "ground_truth.csv").open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(FIELDS)
            w.writerows(rows)
        for r in rows:
            p = self.dir / "images" / r[0]
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"jpeg")
        self.label_map = {"fox": "fox", "red fox": "fox", "rabbit": "rabbit"}

    def test_collect_caches_and_skips_rejects(self):
        rows = bakeoff.load_kept(self.dir)
        self.assertEqual(len(rows), 2)
        fake = FakeRekognition(
            [[label("Fox", 91, [88, 72])], [label("Hare", 80, [79])]]
        )
        cache = bakeoff.collect(rows, self.dir, fake)
        self.assertEqual(fake.calls, 2)
        again = bakeoff.collect(rows, self.dir, fake)
        self.assertEqual(fake.calls, 2)  # nothing re-sent
        self.assertEqual(cache, again)

    def test_predict_maps_case_insensitively_and_counts_boxes(self):
        rec = {
            "labels": [
                {"name": "Red Fox", "confidence": 90, "instances": [88, 60]},
                {"name": "Animal", "confidence": 99, "instances": []},
            ]
        }
        self.assertEqual(
            bakeoff.predict(rec, self.label_map, {}, 50), {"fox": 2}
        )
        self.assertEqual(
            bakeoff.predict(rec, self.label_map, {}, 70), {"fox": 2}
        )
        self.assertEqual(bakeoff.predict(rec, self.label_map, {}, 95), {})

    def test_label_without_boxes_counts_one(self):
        rec = {"labels": [{"name": "Fox", "confidence": 80, "instances": []}]}
        self.assertEqual(
            bakeoff.predict(rec, self.label_map, {}, 50), {"fox": 1}
        )

    def test_hare_goes_to_fallback_not_rabbit(self):
        rec = {
            "labels": [{"name": "Hare", "confidence": 85, "instances": [80]}]
        }
        tags = bakeoff.predict(rec, self.label_map, {}, 50)
        self.assertEqual(tags, {})
        self.assertTrue(bakeoff.to_fallback(rec, tags, ["Hare", "Frog"]))

    def test_score_writes_summary_and_results(self):
        rows = bakeoff.load_kept(self.dir)
        fake = FakeRekognition(
            [[label("Fox", 91, [88, 72])], [label("Rabbit", 62, [60])]]
        )
        cache = bakeoff.collect(rows, self.dir, fake)
        bakeoff.score_report(
            rows, cache, self.label_map, ["Hare"], 1.0, self.dir
        )
        best, _ = bakeoff.suggest_thresholds(rows, cache, self.label_map)
        # Fox 91 on the fox photo: highest threshold that still finds it.
        self.assertEqual(best["fox"], 90)
        # Rabbit 62 on the hare photo must not get through.
        self.assertGreaterEqual(best["rabbit"], 65)
        self.assertTrue((self.dir / "bakeoff_summary.md").exists())
        with (self.dir / "bakeoff_results.csv").open() as f:
            results = list(csv.DictReader(f))
        fox = results[0]
        self.assertEqual((fox["hit"], fox["count_ok"]), ("True", "True"))

    def test_borrow_counts_boxes_from_wrongly_named_animal(self):
        toads = {
            "labels": [
                {
                    "name": "Toad",
                    "confidence": 93,
                    "instances": [],
                    "parents": ["Amphibian", "Animal"],
                },
                {
                    "name": "Lizard",
                    "confidence": 99,
                    "instances": [97, 90, 88],
                    "parents": ["Animal", "Reptile"],
                },
                {
                    "name": "Plant",
                    "confidence": 66,
                    "instances": [70, 60],
                    "parents": [],
                },
            ]
        }
        label_map = {"toad": "cane toad"}
        self.assertEqual(
            bakeoff.predict(toads, label_map, {}, 60), {"cane toad": 1}
        )
        self.assertEqual(
            bakeoff.predict(toads, label_map, {}, 60, borrow=True),
            {"cane toad": 3},  # Lizard boxes, not the Plant ones
        )

    def test_borrow_skips_boxes_a_predicted_tag_already_uses(self):
        rec = {
            "labels": [
                {
                    "name": "Fox",
                    "confidence": 98,
                    "instances": [],
                    "parents": ["Animal", "Mammal"],
                },
                {
                    "name": "Dog",
                    "confidence": 97,
                    "instances": [95, 94],
                    "parents": ["Animal", "Canine"],
                },
            ]
        }
        label_map = {"fox": "fox", "dog": "dog"}
        # Dog is predicted too, so its boxes stay with dog.
        self.assertEqual(
            bakeoff.predict(rec, label_map, {}, 90, borrow=True),
            {"fox": 1, "dog": 2},
        )
        # With a dog threshold above 97, the Dog boxes are free to borrow.
        self.assertEqual(
            bakeoff.predict(rec, label_map, {"dog": 99}, 90, borrow=True),
            {"fox": 2},
        )

    def test_own_boxes_beat_borrowed(self):
        rec = {
            "labels": [
                {
                    "name": "Pig",
                    "confidence": 99,
                    "instances": [99, 98],
                    "parents": ["Animal", "Mammal"],
                },
                {
                    "name": "Bear",
                    "confidence": 96,
                    "instances": [90, 90, 90],
                    "parents": ["Animal", "Mammal"],
                },
            ]
        }
        self.assertEqual(
            bakeoff.predict(rec, {"pig": "feral pig"}, {}, 60, borrow=True),
            {"feral pig": 2},
        )


if __name__ == "__main__":
    unittest.main()
