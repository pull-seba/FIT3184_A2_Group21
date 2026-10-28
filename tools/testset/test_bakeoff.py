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
            bakeoff.predict(rec, self.label_map, {}, 70), {"fox": 1}
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
        bakeoff.score_report(rows, cache, self.label_map, ["Hare"], 0, self.dir)
        best, _ = bakeoff.suggest_thresholds(rows, cache, self.label_map)
        self.assertEqual(
            best["rabbit"], 65
        )  # first threshold above the 62 hare
        self.assertTrue((self.dir / "bakeoff_summary.md").exists())
        with (self.dir / "bakeoff_results.csv").open() as f:
            results = list(csv.DictReader(f))
        fox = results[0]
        self.assertEqual((fox["hit"], fox["count_ok"]), ("True", "True"))


if __name__ == "__main__":
    unittest.main()
