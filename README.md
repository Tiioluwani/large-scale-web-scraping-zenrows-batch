# Zenrows Batch API — example scripts

Runnable companion code for a tutorial on [Zenrows Batch](https://docs.zenrows.com/batch/introduction), Zenrows' async API for scraping large lists of URLs as one managed job.

> **Batch is in beta.** Endpoints, response shapes, and error codes may change. A few things in these examples were adjusted after finding real behavior that didn't match the published docs — see the comments in each script for specifics.

## Prerequisites

- Python 3.9+
- A Zenrows API key ([sign up](https://www.zenrows.com/) if you don't have one)

```bash
pip install -r requirements.txt
cp .env.example .env
# then edit .env and set ZENROWS_API_KEY=your_key_here
```

Each script is runnable on its own (`python 01_cloudflare_target.py`) and writes its raw request/response JSON to a local `results/` folder as it runs, so you can inspect exactly what the API returned.

## Scripts

| Script | Demonstrates |
|---|---|
| `client.py` | Shared helper: auth, job submission/polling, result pagination, reruns, webhooks, HMAC keys, CSV upload, scheduling, and the client-side cost estimator. Imported by every example below. |
| `01_cloudflare_target.py` | Submitting a closed job with `mode: "auto"` against a Cloudflare-protected page, polling to completion, and checking the result content for a bypass confirmation. |
| `02_volume_run.py` | Collecting real URLs by paginating a listing page, submitting them as one batch job, and comparing the client-side cost estimate against actual credits spent. |
| `03_failure_and_rerun.py` | Handling per-task failures (`error.code` / `error.detail`) and re-running just the failed tasks with `POST /jobs/{id}/rerun?status=failed`. Also shows what happens when a URL is malformed rather than just unreachable. |
| `04_extraction.py` | Using `css_extractor` and `autoparse` as job-level `zenrows_params` on a Batch job, and the actual shape of the structured data each one returns. |
| `05_webhook.py` | Attaching a signed webhook (`signature: true`) to a job and verifying the `X-Signature` HMAC on the `run.completed` delivery. |
| `06_diy_comparison.py` | A plain `asyncio`/`aiohttp` scraper with retries and a concurrency semaphore, no Zenrows involved — for comparing against `01_cloudflare_target.py`. |
| `07_csv_upload.py` | The three-step CSV upload flow: create an upload slot, `PUT` the file to a presigned URL, then submit a job referencing `file_input_id`. |
| `08_scheduling.py` | Creating a recurring scheduled job, pausing it, and replacing its schedule — with safety-first ordering so nothing is left active and billing after the script exits. |

## Notes

- Scripts that scrape real pages spend real credits on your account. `01`, `02`, `05`, `07`, and `08` all submit at least one job.
- `08_scheduling.py` pauses the schedule it creates before the script exits, but the (paused) job remains in your account — delete it from the Zenrows dashboard if you want it gone entirely.
- `results/` is git-ignored; treat it as scratch output, not something to commit.
