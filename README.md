# FIT3184_A2_Group21
Aussie EcoGuard is a multi-cloud serverless platform tracking pests and lost pets. Built across AWS and GCP, it uses Cognito for security. Media uploads trigger functions to auto-tag species using ML. Users can search via APIs, use a chatbot to find pets, and receive email alerts.   

To review test-set labels interactively, run:

```sh
python3 prepare_review.py --serve
```

Open http://127.0.0.1:8765/review.html. Each image has a count field, a condition
choice, and a review-status selector. Filter by animal group, status, or filename.
Click **Save CSV** to update `ecoguard_testset/ground_truth.csv` directly. Only edited
counts, conditions, and verification statuses are written; source metadata and other
rows are preserved. A stale edit is refused if its labels changed on disk. Keep the
server running while editing; restart the command whenever needed.

You can also open `ecoguard_testset/review.html` directly and use **Download edited
CSV**, then replace the original CSV with the downloaded file. Downloads include all
rows and columns. Choose exactly one condition: `clear` for easy, well-lit photos;
`night` for dark or infrared photos; or `other` for every other difficult photo,
including small, hidden, blurry, oddly posed or dead animals. Use `true_count` for
multiple animals. Editing counts or conditions does not mark images verified.

Run save-validation checks with `python3 -m unittest test_prepare_review.py`.
