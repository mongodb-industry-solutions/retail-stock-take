# Curated sample-shelf gallery (local)

Drop the shelf photos you want presenters to quick-pick here. These are the
images behind the **Sample** button in the Capture panel.

- The backend serves this gallery read-only via `GET /api/sample-shelves`
  (+ `/api/sample-shelves/image`), gated by `STORAGE_SAMPLES_PREFIX`.
- Locally, `scripts/setup.sh` seeds these files into the in-cluster SeaweedFS
  `store-media` bucket under the `sample-shelves/` prefix (see
  `scripts/seed-samples.sh`), so the local demo matches the deployed one.
- In the cloud, the equivalent set lives in S3 under
  `industry/mobile/retail-stock-take/sample-shelves/` (same read-only endpoints).

Keep it light — a handful of images is plenty (this repo ships **4**).

## Adding images

- Formats: `.jpg` / `.jpeg` / `.png`. The filename becomes the label shown in
  the picker, so name them meaningfully (e.g. `cereal-aisle.jpg`).
- Prefer **stocked** shelves with visible products — the local CV model
  (Ollama / Moondream) is weaker than the cloud one and returns few or zero
  items for empty/blank shelves.
- Keep files reasonably small (a few hundred KB each) — they are committed.

After adding/replacing images, re-seed without a full rebuild:

```bash
./scripts/seed-samples.sh
# or re-run the whole bring-up:
./scripts/setup.sh
```
