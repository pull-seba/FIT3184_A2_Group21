---
paths:
  - "frontend/**"
---

# Frontend (rubric 3.1 to 3.4, 1.2)

- Every API call goes through `src/app/api/` (member 1), which attaches the Cognito ID token and sends a `401` back to sign-in. Don't call `fetch` on the gateway directly.
- Every page except sign-in and sign-up sits inside the auth guard.
- Show results only through the shared gallery in `src/app/components/gallery/` (member 4). Add actions to it; don't build another gallery.
- Upload: hash with `crypto.subtle.digest("SHA-256", ...)`, call `/uploads/init`, then PUT with `XMLHttpRequest` for progress, sending exactly the headers the response lists.
- Photos sent to search are resized in a canvas to about 1024 px JPEG before base64 encoding, which also strips location metadata.
- Every view handles loading, empty, error and success states and updates without a manual refresh.
- Only public identifiers go in the Angular environment files under `src/environments/` (user pool ID, client ID, identity pool ID, gateway URL). No secrets in the bundle.
- Thumbnails get alt text from their tags; controls are reachable by keyboard and have labels.
- Each page lives in its own folder under `src/app/pages/`, owned by the feature's owner; ask member 1 to add routes.
