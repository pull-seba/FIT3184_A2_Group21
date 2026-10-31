#!/usr/bin/env python3
"""
FIT3184 Phase 1 - speed up labelling of the test set.

Works on <out>/ground_truth.csv made by download_testset.py. It can:
  --prefill   fill BLANK true_count (1, or 0 for negative classes) and condition ("clear")
              Never overwrites anything you've already entered.
  --set       quick edits without opening the CSV, e.g.
                --set fox_017:verified=reject
                --set fox_018:condition=other
                --set fox_002,fox_003,fox_005:condition=night
                --set cat_004:role=pet
              Format is  ID[,ID...]:column=value   (ID = filename without extension).
              Values are validated the same way as in the editor (see below).
  --mark-ok   once you've reviewed everything, set verified=ok on every row that is blank
  --serve     edit counts, tags and verification in a browser; save directly to CSV
  (always)    rebuild <out>/review.html - a contact sheet you open in a browser, with the
              file number, count and condition under every image, rejected ones dimmed

Typical use:
  python prepare_review.py --serve
  (open http://127.0.0.1:8765/review.html, edit labels, click Save CSV)
  # Or use the static review.html and download an edited CSV copy.
  python prepare_review.py --prefill
  (open data/review.html, note exceptions)
  python prepare_review.py --set fox_017:verified=reject --set fox_002,fox_003:condition=night
  (re-open review.html to check)  ->  python prepare_review.py --mark-ok

Allowed values:
  condition  exactly one of: clear | night | other   (blank only for rejected rows)
             multiple animals are recorded in true_count, not as a condition
  true_count whole number >= 0; must be 0 when species is "none"
  verified   blank | ok | review | reject | ai | spot
  role       pest | pet | pet/pest | negative
"""

import argparse
import csv
import json
import os
import shutil
import sys
import tempfile
from collections import Counter
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

# Labels live in data/ next to these scripts; images stay local (see .gitignore).
DATA_DIR = Path(__file__).resolve().parent / "data"

FIELDS = [
    "filename",
    "species",
    "true_count",
    "condition",
    "role",
    "common_name",
    "scientific_name",
    "source",
    "licence",
    "attribution",
    "observation_url",
    "photo_id",
    "verified",
]


def load_rows(path):
    if not path.exists():
        sys.exit(
            f"{path} not found - run download_testset.py first (or pass --out)"
        )
    with path.open(newline="", encoding="utf-8") as f:
        return [dict(row) for row in csv.DictReader(f)]


def save_rows(path, rows):
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else FIELDS)
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
        sys.exit(
            f"Bad --set '{spec}'. Use ID[,ID...]:column=value, e.g. fox_017:verified=reject"
        )
    col = col.strip()
    if col not in FIELDS or col == "filename":
        sys.exit(
            f"Can't set column '{col}'. Choose from: {', '.join(f for f in FIELDS if f != 'filename')}"
        )
    by_stem = {Path(r["filename"]).stem: r for r in rows}
    for i in (x.strip() for x in ids_part.split(",") if x.strip()):
        if i not in by_stem:
            print(f"  ! no image named '{i}' - skipped")
            continue
        try:
            check_value(by_stem[i], col, val.strip())
        except ValueError as error:
            sys.exit(f"Bad --set '{spec}': {error}")
        by_stem[i][col] = val.strip()


def build_html(rows, out_dir):
    template = (
        Path(__file__)
        .with_name("review_template.html")
        .read_text(encoding="utf-8")
    )
    data = json.dumps(
        {"fields": list(rows[0]) if rows else FIELDS, "rows": rows},
        ensure_ascii=False,
    )
    data = (
        data.replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
    )
    path = out_dir / "review.html"
    path.write_text(
        template.replace("__DATASET_JSON__", data), encoding="utf-8"
    )
    return path


EDITABLE = {"true_count", "condition", "verified"}
CONDITIONS = {
    "clear",
    "night",
    "other",
}  # exactly one; multiple animals live in true_count
VERIFIED = {"", "ok", "review", "reject", "ai", "spot"}
ROLES = {"pest", "pet", "pet/pest", "negative"}


def check_value(row, col, value):
    """Raise ValueError if value is not allowed in this column for this row."""
    name = row["filename"]
    if col == "true_count":
        if value and (not value.isascii() or not value.isdigit()):
            raise ValueError(
                f"{name}: count must be a nonnegative whole number or blank."
            )
        if row["species"] == "none" and value != "0":
            raise ValueError(f"{name}: negative images must have count 0.")
    elif col == "condition":
        if value not in CONDITIONS and not (value == "" and is_rejected(row)):
            raise ValueError(
                f"{name}: condition must be exactly one of clear, night or other."
            )
    elif col == "verified":
        if value not in VERIFIED:
            raise ValueError(f"{name}: invalid verification status.")
    elif col == "role":
        if value not in ROLES:
            raise ValueError(
                f"{name}: role must be one of {', '.join(sorted(ROLES))}."
            )


def save_edits(out_dir, updates):
    """Apply only explicit edits, rejecting stale values before writing anything."""
    if not isinstance(updates, list) or not updates:
        raise ValueError("No edits supplied.")
    csv_path = out_dir / "ground_truth.csv"
    rows = load_rows(csv_path)
    by_name = {row["filename"]: row for row in rows}
    seen = set()
    for update in updates:
        if not isinstance(update, dict) or set(update) != {
            "filename",
            "before",
            "changes",
        }:
            raise ValueError("Invalid edit format.")
        name, before, changes = (
            update["filename"],
            update["before"],
            update["changes"],
        )
        if not isinstance(name, str) or name not in by_name or name in seen:
            raise ValueError("Unknown or duplicate filename.")
        seen.add(name)
        if (
            not isinstance(changes, dict)
            or not changes
            or not set(changes) <= EDITABLE
        ):
            raise ValueError(
                "Only count, condition and verification can be edited."
            )
        if not isinstance(before, dict) or set(before) != EDITABLE:
            raise ValueError("Missing original labels.")
        row = by_name[name]
        if any(row[key] != before[key] for key in EDITABLE):
            raise ValueError(
                f"{name} changed on disk. Reload before saving; no edits were written."
            )
        if any(not isinstance(value, str) for value in changes.values()):
            raise ValueError("Label values must be strings.")
        # Check against the row as it will be after this edit (e.g. a blank condition
        # is only allowed when the same edit also rejects the row).
        after = {**row, **changes}
        for key, value in changes.items():
            check_value(after, key, value)
        row.update(changes)
    backup = out_dir / "ground_truth.backup.csv"
    if not backup.exists():
        shutil.copyfile(csv_path, backup)
    fd, temporary = tempfile.mkstemp(
        prefix=".ground_truth-", suffix=".csv", dir=out_dir
    )
    os.close(fd)
    try:
        save_rows(Path(temporary), rows)
        os.replace(temporary, csv_path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return rows


def serve_review(out_dir, port):
    out_dir = out_dir.resolve()

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(out_dir), **kwargs)

        def end_headers(self):
            self.send_header("Cache-Control", "no-store")
            super().end_headers()

        def reply(self, status, payload):
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/api/ground-truth":
                rows = load_rows(out_dir / "ground_truth.csv")
                self.reply(
                    200,
                    {"rows": rows, "fields": list(rows[0]) if rows else FIELDS},
                )
            else:
                super().do_GET()

        def do_POST(self):
            if self.path != "/api/ground-truth":
                self.reply(404, {"error": "Unknown endpoint."})
                return
            expected_origin = f"http://{self.headers.get('Host')}"
            allowed_hosts = {
                f"127.0.0.1:{self.server.server_port}",
                f"localhost:{self.server.server_port}",
            }
            if (
                self.headers.get("Host") not in allowed_hosts
                or self.headers.get("Origin") != expected_origin
                or self.headers.get("Content-Type") != "application/json"
            ):
                self.reply(403, {"error": "Save from the local review sheet."})
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 1024 * 1024:
                    raise ValueError("Invalid request size.")
                body = json.loads(self.rfile.read(size))
                if not isinstance(body, dict) or set(body) != {"updates"}:
                    raise ValueError("Invalid save request.")
                rows = save_edits(out_dir, body["updates"])
            except (ValueError, TypeError, KeyError) as error:
                self.reply(400, {"error": str(error)})
                return
            except OSError:
                self.reply(
                    500,
                    {
                        "error": "Could not write ground_truth.csv. Your edits are still on screen."
                    },
                )
                return
            # The CSV has committed; an HTML refresh failure must not report a failed save.
            try:
                build_html(rows, out_dir)
            except OSError:
                pass
            self.reply(
                200, {"rows": rows, "fields": list(rows[0]) if rows else FIELDS}
            )

    server = HTTPServer(("127.0.0.1", port), Handler)
    print(
        f"Review editor: http://127.0.0.1:{server.server_port}/review.html",
        flush=True,
    )
    print(
        "Save CSV writes directly to ground_truth.csv. Stop with Ctrl+C.",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--out", default=str(DATA_DIR))
    ap.add_argument(
        "--prefill",
        action="store_true",
        help="fill blank true_count / condition with defaults",
    )
    ap.add_argument(
        "--set",
        action="append",
        default=[],
        metavar="IDS:col=val",
        help="quick edit (repeatable)",
    )
    ap.add_argument(
        "--mark-ok",
        action="store_true",
        help="set verified=ok on rows still blank",
    )
    ap.add_argument(
        "--serve",
        action="store_true",
        help="open a local editor with direct CSV saving",
    )
    ap.add_argument(
        "--port",
        type=int,
        default=8765,
        help="local editor port (default 8765)",
    )
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

    if args.set or args.prefill or args.mark_ok:
        backup = out / "ground_truth.backup.csv"
        if not backup.exists():
            shutil.copyfile(csv_path, backup)
        save_rows(csv_path, rows)
    sheet = build_html(rows, out)

    kept = [r for r in rows if not is_rejected(r)]
    print(f"\n{len(kept)} images kept, {len(rows) - len(kept)} rejected")
    tags = Counter(
        t.strip() for r in kept for t in r["condition"].split(";") if t.strip()
    )
    if tags:
        print(
            "Condition tags:",
            ", ".join(f"{t} x{n}" for t, n in tags.most_common()),
        )
    print(f"Contact sheet: {sheet}  (open it in your browser)")
    if args.serve:
        serve_review(out, args.port)


if __name__ == "__main__":
    main()
