#!/usr/bin/env python3
"""
Member 3 - Rekognition pilot and bake-off on the hand-labelled test set.

  1. pilot  see which label names Rekognition uses (3 kept images per class)
            python3 tools/testset/bakeoff.py pilot
  2. run    send every kept image once (132 calls, a few cents)
            python3 tools/testset/bakeoff.py run
  3. score  compare with ground_truth.csv using shared/tags.json, suggest a
            confidence threshold per tag, write results for the report
            python3 tools/testset/bakeoff.py score

Every response is cached in data/rekognition_raw.jsonl, one line per image, so
nothing is paid for twice and `score` works offline. --refresh calls again.

AWS: region us-east-1, credentials from the usual boto3 chain, e.g.
  AWS_PROFILE=ecoguard python3 tools/testset/bakeoff.py pilot
Needs `pip install boto3` (and Pillow only if an image is over 5 MB).
"""

import argparse
import csv
import io
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
TAGS_JSON = HERE.parents[1] / "shared" / "tags.json"
REGION = "us-east-1"
MAX_BYTES = 5 * 1024 * 1024  # Rekognition's limit for image bytes
RECORD_MIN_CONFIDENCE = 50  # keep everything >= 50 so thresholds can be swept
THRESHOLDS = [50, 55, 60, 65, 70, 75, 80, 85, 90, 95]
FALLBACK_LABELS = ["Frog", "Amphibian", "Hare", "Canine"]
# Likely Rekognition names for our tags; the pilot shows which really appear.
CANDIDATES = {
    "fox": "fox",
    "red fox": "fox",
    "cat": "cat",
    "kitten": "cat",
    "dog": "dog",
    "puppy": "dog",
    "rabbit": "rabbit",
    "bunny": "rabbit",
    "pig": "feral pig",
    "hog": "feral pig",
    "boar": "feral pig",
    "wild boar": "feral pig",
    "toad": "cane toad",
}


# ---------- data ----------


def load_kept(data_dir):
    path = data_dir / "ground_truth.csv"
    with path.open(newline="", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r["verified"] != "reject"]
    missing = [
        r["filename"]
        for r in rows
        if not (data_dir / "images" / r["filename"]).exists()
    ]
    if missing:
        sys.exit(
            f"{len(missing)} images missing under {data_dir / 'images'}, "
            f"e.g. {missing[0]}"
        )
    return rows


def folder(row):
    return row["filename"].split("/")[0]


def load_label_map(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    mapping = data.get("model_label_map", data)
    return {name.lower(): tag for name, tag in mapping.items()}


# ---------- Rekognition ----------


def image_bytes(path):
    data = path.read_bytes()
    if len(data) <= MAX_BYTES:
        return data
    from PIL import Image  # only needed for oversized images

    img = Image.open(path)
    img.thumbnail((2048, 2048))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=90)
    return buf.getvalue()


def make_client(region):
    try:
        import boto3
    except ImportError:
        sys.exit("pip install boto3")
    return boto3.client("rekognition", region_name=region)


def detect(client, path):
    resp = client.detect_labels(
        Image={"Bytes": image_bytes(path)},
        MaxLabels=100,
        MinConfidence=RECORD_MIN_CONFIDENCE,
    )
    labels = []
    for label in resp["Labels"]:
        labels.append(
            {
                "name": label["Name"],
                "confidence": round(label["Confidence"], 2),
                "instances": [
                    round(i["Confidence"], 2)
                    for i in label.get("Instances", [])
                ],
                "parents": [p["Name"] for p in label.get("Parents", [])],
                "aliases": [a["Name"] for a in label.get("Aliases", [])],
            }
        )
    return {
        "labels": labels,
        "label_model_version": resp.get("LabelModelVersion", ""),
    }


def load_cache(path):
    cache = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                record = json.loads(line)
                cache[record["filename"]] = record  # later lines win
    return cache


def collect(rows, data_dir, client, refresh=False):
    cache_path = data_dir / "rekognition_raw.jsonl"
    cache = load_cache(cache_path)
    todo = [r for r in rows if refresh or r["filename"] not in cache]
    for n, row in enumerate(todo, 1):
        try:
            result = detect(client, data_dir / "images" / row["filename"])
        except Exception as error:  # credentials, permissions, throttling
            sys.exit(
                f"Rekognition call failed on {row['filename']}: {error}\n"
                "Check AWS_PROFILE / credentials, region us-east-1 and "
                "rekognition:DetectLabels permission. Calls made so far "
                "are cached."
            )
        record = {"filename": row["filename"], **result}
        with cache_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
        cache[row["filename"]] = record
        print(f"  [{n}/{len(todo)}] {row['filename']}")
    print(f"{len(todo)} new Rekognition calls, {len(rows) - len(todo)} cached")
    return cache


# ---------- pilot report ----------


def pilot_report(rows, cache, label_map, fallback):
    fallback_l = {f.lower() for f in fallback}
    seen_targets = Counter()
    print("\nLabels per class (images seen / mean confidence / mapping):")
    for cls in sorted({folder(r) for r in rows}):
        recs = [cache[r["filename"]] for r in rows if folder(r) == cls]
        stats = defaultdict(list)
        boxes = Counter()
        for rec in recs:
            for label in rec["labels"]:
                stats[label["name"]].append(label["confidence"])
                if label["instances"]:
                    boxes[label["name"]] += 1
        print(f"\n  {cls} ({len(recs)} images)")
        ranked = sorted(
            stats.items(), key=lambda kv: (-len(kv[1]), -max(kv[1]))
        )

        def relevant(name):
            key = name.lower()
            return key in label_map or key in fallback_l or key in CANDIDATES

        # Top 12, plus any mapped / candidate / fallback label further down.
        shown = ranked[:12] + [kv for kv in ranked[12:] if relevant(kv[0])]
        for name, confs in shown:
            key = name.lower()
            if key in label_map:
                note = f"-> {label_map[key]}"
            elif key in fallback_l:
                note = "(fallback)"
            elif key in CANDIDATES:
                note = f"(candidate -> {CANDIDATES[key]}, not in map)"
            else:
                note = ""
            box = f", boxes on {boxes[name]}" if boxes[name] else ""
            print(
                f"    {name:<22} {len(confs)}/{len(recs)}  "
                f"{sum(confs) / len(confs):5.1f}{box}  {note}"
            )
        if not cls.startswith("neg_"):
            for name, confs in stats.items():
                seen_targets[name] += len(confs)

    suggested = {
        name.lower(): CANDIDATES[name.lower()]
        for name in seen_targets
        if name.lower() in CANDIDATES
    }
    print(
        "\nDraft model_label_map (candidate names Rekognition actually used):"
    )
    print(json.dumps(dict(sorted(suggested.items())), indent=2))
    covered = set(suggested.values())
    expected = {
        "fox",
        "cat",
        "dog",
        "rabbit",
        "feral pig",
        "cane toad",
    }
    for tag in sorted(expected - covered):
        print(
            f"  ! nothing seen maps to '{tag}' yet - look at that class's "
            "labels above for its name"
        )
    print(
        "\nFallback-type labels seen: "
        + (
            ", ".join(
                sorted(n for n in seen_targets if n.lower() in fallback_l)
            )
            or "none"
        )
    )


# ---------- scoring ----------


def predict(record, label_map, thresholds, default_threshold):
    """Returns ({tag: count}, sent_to_fallback) for one image."""
    tags = {}
    for label in record["labels"]:
        tag = label_map.get(label["name"].lower())
        if not tag:
            continue
        threshold = thresholds.get(tag, default_threshold)
        if label["confidence"] < threshold:
            continue
        boxes = sum(1 for c in label["instances"] if c >= threshold)
        tags[tag] = max(tags.get(tag, 0), boxes or 1)
    return tags


def to_fallback(record, tags, fallback, threshold=RECORD_MIN_CONFIDENCE):
    names = {f.lower() for f in fallback}
    return not tags and any(
        label["name"].lower() in names and label["confidence"] >= threshold
        for label in record["labels"]
    )


def evaluate(rows, cache, label_map, thresholds, default_threshold):
    out = []
    for row in rows:
        rec = cache[row["filename"]]
        tags = predict(rec, label_map, thresholds, default_threshold)
        truth = row["species"]
        hit = truth != "none" and truth in tags
        out.append(
            {
                "row": row,
                "tags": tags,
                "hit": hit,
                "count_ok": hit and tags[truth] == int(row["true_count"]),
                "false_tags": [t for t in tags if t != truth],
            }
        )
    return out


def suggest_thresholds(rows, cache, label_map, max_false=0):
    """Per tag: lowest threshold whose false tags on other images <= max_false."""
    tags = sorted(set(label_map.values()))
    best = {}
    sweep = {}
    for tag in tags:
        sweep[tag] = []
        for t in THRESHOLDS:
            results = evaluate(rows, cache, label_map, {tag: t}, t)
            n = sum(1 for r in results if r["row"]["species"] == tag)
            hits = sum(
                1 for r in results if r["row"]["species"] == tag and r["hit"]
            )
            false = sum(1 for r in results if tag in r["false_tags"])
            sweep[tag].append((t, hits, n, false))
        ok = [s for s in sweep[tag] if s[3] <= max_false]
        best[tag] = ok[0][0] if ok else THRESHOLDS[-1]
    return best, sweep


def pct(a, b):
    return f"{100 * a / b:.0f}%" if b else "-"


def score_report(rows, cache, label_map, fallback, max_false, data_dir):
    best, sweep = suggest_thresholds(rows, cache, label_map, max_false)
    lines = ["# Rekognition bake-off", ""]
    lines += [
        "Recall = share of that species' images where the tag was found. "
        "False = images of something else that got this tag.",
        "",
        "## Threshold sweep",
        "",
        "| Tag | " + " | ".join(str(t) for t in THRESHOLDS) + " |",
        "| --- |" + " --- |" * len(THRESHOLDS),
    ]
    for tag, points in sweep.items():
        cells = [f"{pct(h, n)} / {f}" for _, h, n, f in points]
        lines.append(f"| {tag} (recall / false) | " + " | ".join(cells) + " |")

    results = evaluate(rows, cache, label_map, best, THRESHOLDS[-1])
    lines += [
        "",
        f"## At the suggested per-tag thresholds (max {max_false} false)",
        "",
        "| Tag | Threshold | Images | Recall | Count exact | Recall clear "
        "| Recall night | Recall other |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for tag in sorted(best):
        mine = [r for r in results if r["row"]["species"] == tag]
        hits = [r for r in mine if r["hit"]]
        by_cond = []
        for cond in ("clear", "night", "other"):
            sub = [r for r in mine if r["row"]["condition"] == cond]
            by_cond.append(pct(sum(r["hit"] for r in sub), len(sub)))
        lines.append(
            f"| {tag} | {best[tag]} | {len(mine)} | "
            f"{pct(len(hits), len(mine))} | "
            f"{pct(sum(r['count_ok'] for r in hits), len(hits))} | "
            + " | ".join(by_cond)
            + " |"
        )
    negatives = [r for r in results if r["row"]["species"] == "none"]
    fp_neg = [r for r in negatives if r["tags"]]
    sent = [
        r
        for r in results
        if to_fallback(cache[r["row"]["filename"]], r["tags"], fallback)
    ]
    missed = [
        r for r in results if r["row"]["species"] != "none" and not r["hit"]
    ]
    lines += [
        "",
        f"- Negative images given a target tag: {len(fp_neg)} of "
        f"{len(negatives)}"
        + (
            " ("
            + ", ".join(
                f"{Path(r['row']['filename']).stem}: {', '.join(r['tags'])}"
                for r in fp_neg
            )
            + ")"
            if fp_neg
            else ""
        ),
        f"- Images with no mapped tag but a fallback label "
        f"({', '.join(fallback)}): {len(sent)}",
        f"- Target images missed: {len(missed)}",
        "",
        "## Misses (top Rekognition labels)",
        "",
    ]
    for r in missed:
        top = sorted(
            cache[r["row"]["filename"]]["labels"],
            key=lambda x: -x["confidence"],
        )[:5]
        lines.append(
            f"- {r['row']['filename']} ({r['row']['condition']}): "
            + ", ".join(f"{x['name']} {x['confidence']:.0f}" for x in top)
        )

    summary = data_dir / "bakeoff_summary.md"
    summary.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with (data_dir / "bakeoff_results.csv").open(
        "w", newline="", encoding="utf-8"
    ) as f:
        w = csv.writer(f)
        w.writerow(
            [
                "filename",
                "species",
                "true_count",
                "condition",
                "predicted",
                "hit",
                "count_ok",
                "false_tags",
                "to_fallback",
                "top_labels",
            ]
        )
        for r in results:
            rec = cache[r["row"]["filename"]]
            top = sorted(rec["labels"], key=lambda x: -x["confidence"])[:5]
            w.writerow(
                [
                    r["row"]["filename"],
                    r["row"]["species"],
                    r["row"]["true_count"],
                    r["row"]["condition"],
                    ";".join(f"{t}:{c}" for t, c in r["tags"].items()),
                    r["hit"],
                    r["count_ok"],
                    ";".join(r["false_tags"]),
                    to_fallback(rec, r["tags"], fallback),
                    "; ".join(
                        f"{x['name']} {x['confidence']:.0f}" for x in top
                    ),
                ]
            )
    print("\n".join(lines))
    print(f"\nWrote {summary} and {data_dir / 'bakeoff_results.csv'}")
    print("Suggested thresholds for config/model:", json.dumps(best))


# ---------- main ----------


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("mode", choices=["pilot", "run", "score"])
    ap.add_argument("--per-class", type=int, default=3, help="pilot size")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--refresh", action="store_true", help="ignore the cache")
    ap.add_argument(
        "--label-map",
        default=str(TAGS_JSON),
        help="tags.json, or a JSON file of label -> tag to try a draft map",
    )
    ap.add_argument(
        "--fallback",
        default=",".join(FALLBACK_LABELS),
        help="labels that should send an image to the fallback model",
    )
    ap.add_argument(
        "--max-false",
        type=int,
        default=0,
        help="false tags allowed per tag when suggesting thresholds",
    )
    ap.add_argument("--region", default=REGION)
    ap.add_argument("--data", default=str(DATA_DIR))
    args = ap.parse_args()

    data_dir = Path(args.data)
    rows = load_kept(data_dir)
    label_map = load_label_map(args.label_map)
    fallback = [f.strip() for f in args.fallback.split(",") if f.strip()]

    if args.mode == "pilot":
        rng = random.Random(args.seed)
        picked = []
        for cls in sorted({folder(r) for r in rows}):
            members = [r for r in rows if folder(r) == cls]
            picked += rng.sample(members, min(args.per_class, len(members)))
        cache = collect(
            picked, data_dir, make_client(args.region), args.refresh
        )
        pilot_report(picked, cache, label_map, fallback)
    elif args.mode == "run":
        collect(rows, data_dir, make_client(args.region), args.refresh)
        print("Next: python3 tools/testset/bakeoff.py score")
    else:
        cache = load_cache(data_dir / "rekognition_raw.jsonl")
        missing = [r for r in rows if r["filename"] not in cache]
        if missing:
            sys.exit(
                f"{len(missing)} images have no Rekognition result yet - "
                "run `bakeoff.py run` first"
            )
        score_report(rows, cache, label_map, fallback, args.max_false, data_dir)


if __name__ == "__main__":
    main()
