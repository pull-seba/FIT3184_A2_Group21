#!/usr/bin/env python3
"""
FIT3184 Phase 1 - speed up labelling of the test set.

Works on <out>/ground_truth.csv made by download_testset.py. It can:
  --prefill   fill BLANK true_count (1, or 0 for negative classes) and condition ("clear")
              Never overwrites anything you've already entered.
  --set       quick edits without opening the CSV, e.g.
                --set fox_017:verified=reject
                --set fox_018:condition=dead
                --set fox_002,fox_003,fox_005:condition=night
              Format is  ID[,ID...]:column=value   (ID = filename without extension).
              Several tags on one image: condition="night;small"
  --mark-ok   once you've reviewed everything, set verified=ok on every row that is blank
  (always)    rebuild <out>/review.html - a contact sheet you open in a browser, with the
              file number, count and condition under every image, rejected ones dimmed

Typical use:
  python prepare_review.py --prefill
  (open ecoguard_testset/review.html, note exceptions)
  python prepare_review.py --set fox_017:verified=reject --set fox_002,fox_003:condition=night
  (re-open review.html to check)  ->  python prepare_review.py --mark-ok
"""
import argparse
import csv
import html
import sys
from collections import Counter
from pathlib import Path

FIELDS = [
    "filename", "species", "true_count", "condition", "role", "common_name",
    "scientific_name", "source", "licence", "attribution", "observation_url",
    "photo_id", "verified",
]


def load_rows(path):
    if not path.exists():
        sys.exit(f"{path} not found - run download_testset.py first (or pass --out)")
    with path.open(newline="", encoding="utf-8") as f:
        return [{k: row.get(k, "") or "" for k in FIELDS} for row in csv.DictReader(f)]


def save_rows(path, rows):
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)


def is_rejected(r):
    return r["verified"].strip().lower() == "reject"


def prefill(rows):
    changed = 0
    for r in rows:
        if is_rejected(r):
            continue
        if not r["true_count"].strip():
            r["true_count"] = "0" if r["role"] == "negative" else "1"
            changed += 1
        if not r["condition"].strip():
            r["condition"] = "clear"
    return changed


def apply_set(rows, spec):
    try:
        ids_part, assign = spec.split(":", 1)
        col, val = assign.split("=", 1)
    except ValueError:
        sys.exit(f"Bad --set '{spec}'. Use ID[,ID...]:column=value, e.g. fox_017:verified=reject")
    col = col.strip()
    if col not in FIELDS or col == "filename":
        sys.exit(f"Can't set column '{col}'. Choose from: {', '.join(f for f in FIELDS if f != 'filename')}")
    by_stem = {Path(r["filename"]).stem: r for r in rows}
    for i in (x.strip() for x in ids_part.split(",") if x.strip()):
        if i not in by_stem:
            print(f"  ! no image named '{i}' - skipped")
            continue
        by_stem[i][col] = val.strip()


def build_html(rows, out_dir):
    groups = {}
    for r in rows:
        groups.setdefault(r["filename"].split("/")[0], []).append(r)

    parts = ["""<!doctype html><html><head><meta charset="utf-8"><title>Test set review</title>
<style>
body{font-family:Arial,Helvetica,sans-serif;margin:16px;background:#fafafa;color:#222}
h2{margin:28px 0 8px} h2 small{font-weight:normal;color:#666}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:10px}
figure{margin:0;background:#fff;border:1px solid #ddd;border-radius:6px;padding:6px}
figure img{width:100%;height:170px;object-fit:contain;background:#eee;display:block}
figcaption{font-size:12px;line-height:1.5;margin-top:4px}
.reject{opacity:.35} .reject b{text-decoration:line-through}
</style></head><body><h1>Test set review</h1>
<p>Number = filename (e.g. 017 = fox_017). Click an image to open it full size.</p>"""]
    for folder, rs in groups.items():
        kept = sum(1 for r in rs if not is_rejected(r))
        parts.append(f"<h2>{html.escape(folder)} <small>({kept} kept / {len(rs)} total)</small></h2><div class='grid'>")
        for r in rs:
            src = "images/" + html.escape(r["filename"])
            stem = html.escape(Path(r["filename"]).stem)
            cls = "reject" if is_rejected(r) else ""
            parts.append(
                f"<figure class='{cls}'><a href='{src}' target='_blank'><img loading='lazy' src='{src}'></a>"
                f"<figcaption><b>{stem}</b><br>count: {html.escape(r['true_count'] or '?')}"
                f" &middot; {html.escape(r['condition'] or '?')}<br>"
                f"<span style='color:#888'>{html.escape(r['verified'])}</span></figcaption></figure>"
            )
        parts.append("</div>")
    parts.append("</body></html>")
    path = out_dir / "review.html"
    path.write_text("\n".join(parts), encoding="utf-8")
    return path


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="ecoguard_testset")
    ap.add_argument("--prefill", action="store_true", help="fill blank true_count / condition with defaults")
    ap.add_argument("--set", action="append", default=[], metavar="IDS:col=val", help="quick edit (repeatable)")
    ap.add_argument("--mark-ok", action="store_true", help="set verified=ok on rows still blank")
    args = ap.parse_args()

    out = Path(args.out)
    csv_path = out / "ground_truth.csv"
    rows = load_rows(csv_path)

    for spec in args.set:
        apply_set(rows, spec)
    if args.prefill:
        print(f"Prefilled {prefill(rows)} blank true_count cells")
    if args.mark_ok:
        n = 0
        for r in rows:
            if not r["verified"].strip():
                r["verified"] = "ok"
                n += 1
        print(f"Marked {n} rows verified=ok")

    save_rows(csv_path, rows)
    sheet = build_html(rows, out)

    kept = [r for r in rows if not is_rejected(r)]
    print(f"\n{len(kept)} images kept, {len(rows) - len(kept)} rejected")
    tags = Counter(t.strip() for r in kept for t in r["condition"].split(";") if t.strip())
    if tags:
        print("Condition tags:", ", ".join(f"{t} x{n}" for t, n in tags.most_common()))
    print(f"Contact sheet: {sheet}  (open it in your browser)")


if __name__ == "__main__":
    main()