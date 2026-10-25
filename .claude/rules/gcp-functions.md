---
paths:
  - "functions/**"
  - "shared/python/**"
---

# GCP Cloud Run functions

- One folder per function: `functions/<area>/<name>/` with `main.py`, `requirements.txt`, `README.md` and `test_main.py`. Scaffold with `/new-function`. The README states the trigger, the service account and every role it holds.
- HTTP functions read the caller with `ecoguard_common.auth.get_user(request)`. Never decode the `Authorization` header yourself and never trust a user ID sent in the body.
- Validate input and return `400` with the error shape from `docs/contracts/api-routes.md` before touching storage or Firestore.
- Event functions (Eventarc, Pub/Sub) are idempotent: check the current state first and treat "already done" as success.
- Create Firestore and Storage clients once at module level; keep per-request state in local variables.
- Build tag field paths with `firestore.FieldPath("tags", name)`: tag names can contain spaces.
- Sign URLs without key files: refresh the default credentials and pass `service_account_email` and `access_token` to `blob.generate_signed_url(version="v4", ...)`. The function's service account needs Service Account Token Creator on itself.
- Log JSON lines that include `file_id`. Never log tokens, signed URLs or image bytes.
- Tests mock every cloud client. No test touches the shared project.
- `shared/python/ecoguard_common` is copied into the function folder before deploy (the copy is gitignored); never edit the copy.
