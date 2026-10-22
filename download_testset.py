#!/usr/bin/env python3
"""
FIT3184 Phase 1 - build the bake-off test set from iNaturalist.

What it does
  * For each class in SPECIES, finds CC-licensed photos via the public iNaturalist API
  * Downloads them to <out>/images/<folder>/
  * Writes / updates <out>/ground_truth.csv with source + licence filled in

Setup:    pip install requests
Run:      python download_testset.py                   (all classes)
          python download_testset.py --only fox cat    (just some - good for a first test)
          python download_testset.py --per-species 20 --place-id 0   (20 each, worldwide)

Re-running is safe: it only tops up classes that are short and never overwrites
your edits to the CSV. To drop a bad image, set its `verified` cell to "reject"
and re-run; the script will fetch a replacement.

Fill in by hand afterwards: true_count, condition, verified.
"""
import argparse
import csv
import math
import random
import sys
import time
from pathlib import Path

import requests

API = "https://api.inaturalist.org/v1"
HEADERS = {"User-Agent": "FIT3184-EcoGuard-testset/1.0 (student coursework)"}
# Non-commercial CC licences are fine for coursework; check before reusing elsewhere.
LICENSES = "cc0,cc-by,cc-by-nc,cc-by-sa,cc-by-nc-sa"

FIELDS = [
    "filename", "species", "true_count", "condition", "role", "common_name",
    "scientific_name", "source", "licence", "attribution", "observation_url",
    "photo_id", "verified",
]

# Edit this list to match the species list you agree with role 4.
# label = what goes in the `species` column ("none" = no target species expected)
# quality = iNaturalist quality filter; pets are mostly "casual"/captive, so use "any"
SPECIES = [
    dict(folder="cat", label="cat", sci="Felis catus", quality="any", role="pet", common="cat"),  # team decision 22 Oct: cats in this test set are pets
    dict(folder="dog", label="dog", sci="Canis lupus familiaris", quality="any", role="pet", common="dog"),
    dict(folder="fox", label="fox", sci="Vulpes vulpes", quality="research", role="pest", common="red fox"),
    dict(folder="rabbit", label="rabbit", sci="Oryctolagus cuniculus", quality="research", role="pest", common="European rabbit"),
    dict(folder="feral_pig", label="feral pig", sci="Sus scrofa", quality="research", role="pest", common="feral pig / wild boar"),
    dict(folder="cane_toad", label="cane toad", sci="Rhinella marina", quality="research", role="pest", common="cane toad"),
    # Negatives / confusable non-targets: truth is "none"
    dict(folder="neg_kangaroo", label="none", sci="Macropus giganteus", quality="research", role="negative", common="eastern grey kangaroo"),
    dict(folder="neg_wombat", label="none", sci="Vombatus ursinus", quality="research", role="negative", common="common wombat"),
    dict(folder="neg_green_tree_frog", label="none", sci="Litoria caerulea", quality="research", role="negative", common="green tree frog (cane toad lookalike)"),
    dict(folder="neg_hare", label="none", sci="Lepus europaeus", quality="research", role="negative", common="brown hare (rabbit lookalike)"),
]


def api_get(path, **params):
    """GET with gentle rate limiting (iNaturalist asks for <= ~60 requests/min)."""
    for attempt in range(4):
        r = requests.get(f"{API}{path}", params=params, headers=HEADERS, timeout=30)
        if r.status_code == 429:
            time.sleep(5 * (attempt + 1))
            continue
        r.raise_for_status()
        time.sleep(1.0)
        return r.json()
    raise RuntimeError(f"iNaturalist kept rate-limiting {path}; try again in a few minutes")


def resolve_taxon(sci_name):
    results = api_get("/taxa", q=sci_name, is_active="true", per_page=10)["results"]
    if not results:
        sys.exit(f"No iNaturalist taxon found for '{sci_name}'")
    exact = [t for t in results if t["name"].lower() == sci_name.lower()]
    t = (exact or results)[0]
    print(f"  taxon: {t['name']} ({t.get('preferred_common_name')}) id={t['id']}")
    return t["id"]


def fetch_candidates(taxon_id, quality, place_id):
    """Page 1 plus one random later page, so we don't only get the newest uploads."""
    base = dict(taxon_id=taxon_id, photos="true", photo_license=LICENSES,
                quality_grade=quality, per_page=200)
    if place_id:
        base["place_id"] = place_id
    first = api_get("/observations", page=1, **base)
    pool = list(first["results"])
    pages = min(math.ceil(first["total_results"] / 200), 50)
    if pages > 1:
        pool += api_get("/observations", page=random.randint(2, pages), **base)["results"]
    return pool


def to_candidate(obs):
    """First licensed photo of an observation (one photo per observation for variety)."""
    for p in obs.get("photos", []):
        if p.get("license_code") and p.get("url"):
            return dict(
                photo_id=str(p["id"]),
                url=p["url"].replace("/square.", "/large."),  # ~1024px
                licence=p["license_code"],
                attribution=p.get("attribution", ""),
                obs_url=obs.get("uri") or f"https://www.inaturalist.org/observations/{obs['id']}",
            )
    return None


def gather(spec, need, place_id, known_ids):
    taxon_id = resolve_taxon(spec["sci"])
    pool = {}
    # Try the chosen place first; widen to worldwide only if that's too thin.
    for pid in ([place_id, None] if place_id else [None]):
        for obs in fetch_candidates(taxon_id, spec["quality"], pid):
            c = to_candidate(obs)
            if c and c["photo_id"] not in known_ids:
                pool.setdefault(c["photo_id"], c)
        if len(pool) >= need:
            break
    picks = random.sample(list(pool.values()), min(need, len(pool)))
    if len(picks) < need:
        print(f"  ! only found {len(picks)} of {need} - add photos by hand or widen --place-id 0")
    return picks


def download(url, dest):
    for _ in range(3):
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
            r.raise_for_status()
            dest.write_bytes(r.content)
            return True
        except requests.RequestException:
            time.sleep(2)
    return False


def load_rows(path):
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return [{k: row.get(k, "") for k in FIELDS} for row in csv.DictReader(f)]


def save_rows(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)


def next_index(rows, folder):
    nums = [int(Path(r["filename"]).stem.rsplit("_", 1)[1])
            for r in rows if r["filename"].startswith(folder + "/")]
    return max(nums, default=0) + 1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--per-species", type=int, default=18, help="images per target class")
    ap.add_argument("--per-negative", type=int, default=8, help="images per negative class")
    ap.add_argument("--out", default="ecoguard_testset")
    ap.add_argument("--place-id", type=int, default=6744,
                    help="iNaturalist place id (6744 = Australia, 0 = worldwide)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--only", nargs="*", help="folder names to run, e.g. fox cat")
    args = ap.parse_args()

    random.seed(args.seed)
    out = Path(args.out)
    csv_path = out / "ground_truth.csv"
    rows = load_rows(csv_path)

    for spec in SPECIES:
        if args.only and spec["folder"] not in args.only:
            continue
        target = args.per_negative if spec["role"] == "negative" else args.per_species
        in_folder = [r for r in rows if r["filename"].startswith(spec["folder"] + "/")]
        have = [r for r in in_folder if r["verified"].strip().lower() != "reject"]
        known_ids = {r["photo_id"] for r in in_folder}
        need = target - len(have)
        print(f"\n[{spec['folder']}] have {len(have)}, target {target}")
        if need <= 0:
            continue

        picks = gather(spec, need, args.place_id or None, known_ids)
        (out / "images" / spec["folder"]).mkdir(parents=True, exist_ok=True)
        idx = next_index(rows, spec["folder"])
        for c in picks:
            ext = Path(c["url"].split("?")[0]).suffix or ".jpg"
            rel = f"{spec['folder']}/{spec['folder']}_{idx:03d}{ext}"
            if not download(c["url"], out / "images" / rel):
                print(f"  ! download failed: {c['url']}")
                continue
            rows.append(dict(
                filename=rel, species=spec["label"], true_count="", condition="",
                role=spec["role"], common_name=spec["common"], scientific_name=spec["sci"],
                source="iNaturalist", licence=c["licence"], attribution=c["attribution"],
                observation_url=c["obs_url"], photo_id=c["photo_id"], verified="",
            ))
            idx += 1
            time.sleep(0.2)
        save_rows(csv_path, rows)  # save per class so a crash loses nothing
        print(f"  saved {len(picks)} new images")

    print(f"\nDone. Ground truth: {csv_path}")
    print("Next: eyeball every image, fix wrong labels (verified=reject), and fill in")
    print("true_count and condition (close-up / small / occluded / night / blurry / multiple).")


if __name__ == "__main__":
    main()