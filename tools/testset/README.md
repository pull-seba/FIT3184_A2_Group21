# Test set for the detector bake-off (member 3)

Ground truth for checking the tagging models (rubric 2.1.3): 148 photos of the
six tags in `shared/tags.json` plus four lookalike "negative" classes, each
labelled by hand with how many animals of that species it shows.

Only `data/ground_truth.csv` is committed. The images stay local (see
`.gitignore`); every row records its source page, photo ID, licence and credit
line. The original iNaturalist images can be rebuilt with `download_testset.py`;
the manually added images must be downloaded from their recorded source URLs.

## What's in `data/ground_truth.csv`

| Column | Meaning |
| --- | --- |
| `filename` | Path under `data/images/`, e.g. `fox/fox_001.jpg` |
| `species` | A tag from `shared/tags.json`, or `none` for negative classes |
| `true_count` | Animals of that species in the photo; always 0 for `none` |
| `condition` | Exactly one of `clear`, `night` (dark or infrared) or `other` (small, hidden, blurry, odd) |
| `role` | `pest`, `pet` or `negative`; every cat and dog here is a pet |
| `verified` | `ok` = checked by hand; `reject` = excluded (no animal, wrong species) |
| `source`, `licence`, `attribution`, `observation_url`, `photo_id` | Where the photo came from and how to credit it |

Current set: 140 kept (fox 20, cat 16, dog 17, rabbit 18, feral pig 17, cane
toad 20, negatives 32: kangaroo, wombat, green tree frog, hare), 8 rejected.

## Manually added images (28 October 2026)

Imported with `add_images.py`; counts were supplied by Danny. Existing labels
were preserved. Filenames below are relative to `data/images/`.

| Original filename | Dataset filename | Count | Condition |
| --- | --- | --- | --- |
| `foxed-fighting-2.jpg` | `fox/fox_019.jpg` | 2 | other |
| `foxes in belgrave-2.jpg` | `fox/fox_020.jpg` | 2 | night |
| `foxes-2.jpg` | `fox/fox_021.jpg` | 2 | other |
| `3-cane-toads.jpg` | `cane_toad/cane_toad_019.jpg` | 3 | other |
| `cane-6+.jpg` | `cane_toad/cane_toad_020.jpg` | 6 | other |
| `cane toads-2.jpg` | `cane_toad/cane_toad_021.jpg` | 2 | clear |
| `rabbits-12.jpg` | `rabbit/rabbit_019.jpg` | 12 | other |
| `rabbits-11.jpg` | `rabbit/rabbit_020.jpg` | 11 | other |

The crowded toad photo uses the agreed count of 6; overlapping animals make
the total uncertain. Conditions were assigned by visual inspection during
import. New rows use `verified=ok` for the user-supplied labels.

Source URLs and credits are recorded in the CSV. The two John Weeks photos
and Cameron Hudson's three-toad photo have `licence=unconfirmed`; this does
not claim permission has been granted. Other imports use CC BY 2.0 or 3.0.

## Scripts

Run from the repo root. All default to `tools/testset/data/`.

```sh
pip install requests
python3 tools/testset/download_testset.py --only fox     # top up or rebuild a class from iNaturalist
python3 tools/testset/prepare_review.py --serve          # label editor at http://127.0.0.1:8765/review.html
python3 tools/testset/prepare_review.py --set cat_004:role=pet
python3 tools/testset/add_images.py cane_toad ~/Downloads/toads.jpg --count 3 \
    --condition night --source iNaturalist --licence cc-by-nc \
    --attribution "(c) Name, CC BY-NC" --url https://www.inaturalist.org/observations/123
cd tools/testset && python3 -m unittest test_prepare_review.py
```

The editor saves straight to `ground_truth.csv`. Every write path (editor,
`--set`, `add_images.py`) uses the same checks in `check_value()`.
