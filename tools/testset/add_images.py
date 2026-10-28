#!/usr/bin/env python3
"""
FIT3184 Phase 1 - add a hand-picked image to the test set (e.g. a photo with several animals).

Copies the image into data/images/<folder>/<folder>_NNN.<ext>, appends its row to
ground_truth.csv (species, role and names come from the SPECIES list in download_testset.py),
validates it with the same rules as the review editor, and rebuilds review.html.
The row is saved as verified=ok because you have looked at it and counted the animals yourself.

Examples:
  python3 add_images.py cane_toad ~/Downloads/toads.jpg --count 3 --condition night \\
      --source iNaturalist --licence cc-by-nc --attribution "(c) Jane Doe, some rights reserved (CC BY-NC)" \\
      --url https://www.inaturalist.org/observations/123456
  python3 add_images.py fox ~/Downloads/fox-cubs.jpg --count 4 --condition clear \\
      --source Pexels --licence "Pexels licence" --attribution "Photo by John Smith on Pexels" \\
      --url https://www.pexels.com/photo/...

Don't run it while `prepare_review.py --serve` has unsaved edits: save first, add, then reload the page.
"""

import argparse
import shutil
import sys
from pathlib import Path

from download_testset import SPECIES
from prepare_review import FIELDS, build_html, check_value, load_rows, save_rows

# Labels live in data/ next to these scripts; images stay local (see .gitignore).
DATA_DIR = Path(__file__).resolve().parent / "data"

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "folder",
        choices=[s["folder"] for s in SPECIES],
        help="test-set folder, e.g. cane_toad",
    )
    ap.add_argument("image", type=Path, help="path to the image you picked")
    ap.add_argument(
        "--count",
        type=int,
        required=True,
        help="animals of that species in the photo (0 for negatives)",
    )
    ap.add_argument(
        "--condition", required=True, choices=["clear", "night", "other"]
    )
    ap.add_argument(
        "--source",
        required=True,
        help="where it came from, e.g. iNaturalist, Pexels, Wikimedia Commons, own photo",
    )
    ap.add_argument(
        "--licence",
        required=True,
        help='e.g. cc-by, cc-by-nc, cc0, "Pexels licence", own',
    )
    ap.add_argument(
        "--attribution",
        default="",
        help="credit line as the source asks for it",
    )
    ap.add_argument(
        "--url",
        default="",
        help="page the image came from (used to stop duplicates)",
    )
    ap.add_argument("--out", default=str(DATA_DIR))
    args = ap.parse_args()

    spec = next(s for s in SPECIES if s["folder"] == args.folder)
    if not args.image.is_file():
        sys.exit(f"{args.image} not found")
    ext = args.image.suffix.lower()
    if ext not in IMAGE_EXTS:
        sys.exit(
            f"{args.image.name}: expected one of {', '.join(sorted(IMAGE_EXTS))}"
        )
    if args.count < 0:
        sys.exit("--count must be 0 or more")

    out = Path(args.out)
    csv_path = out / "ground_truth.csv"
    rows = load_rows(csv_path)
    if args.url and any(r.get("observation_url") == args.url for r in rows):
        sys.exit(f"{args.url} is already in the test set")

    folder_dir = out / "images" / args.folder
    folder_dir.mkdir(parents=True, exist_ok=True)
    used = [
        int(Path(r["filename"]).stem.rsplit("_", 1)[1])
        for r in rows
        if r["filename"].startswith(args.folder + "/")
    ]
    idx = max(used, default=0) + 1
    while any(folder_dir.glob(f"{args.folder}_{idx:03d}.*")):
        idx += 1
    rel = f"{args.folder}/{args.folder}_{idx:03d}{ext}"

    fields = list(rows[0]) if rows else FIELDS
    row = dict.fromkeys(fields, "")
    row.update(
        filename=rel,
        species=spec["label"],
        true_count=str(args.count),
        condition=args.condition,
        role=spec["role"],
        common_name=spec["common"],
        scientific_name=spec["sci"],
        source=args.source,
        licence=args.licence,
        attribution=args.attribution,
        observation_url=args.url,
        photo_id="",
        verified="ok",
    )
    try:
        for col in ("true_count", "condition", "verified", "role"):
            check_value(row, col, row[col])
    except ValueError as error:
        sys.exit(str(error))

    backup = out / "ground_truth.backup.csv"
    if not backup.exists():
        shutil.copyfile(csv_path, backup)
    shutil.copy2(args.image, out / "images" / rel)
    rows.append(row)
    save_rows(csv_path, rows)
    build_html(rows, out)
    print(f"Added {rel}: {spec['label']} x{args.count}, {args.condition}")


if __name__ == "__main__":
    main()
