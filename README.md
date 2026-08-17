# How to Run Large-Scale Web Scraping Jobs with Zenrows Batch

## Description

This repo is the companion code for a tutorial on [Zenrows Batch](https://docs.zenrows.com/batch/introduction), Zenrows' async API for scraping large lists of URLs as one managed job. You'll build and run eight standalone scripts that submit real Batch jobs, poll them to completion, and inspect the results, covering everything from a single Cloudflare-protected page to a 100-URL volume run.

## Features

- Cloudflare challenge handling via `mode: "auto"`, with credit-tier reporting
- Volume runs across 50-100 real URLs, with a client-side cost estimator checked against actual spend
- Per-task failure inspection (`error.code` / `error.detail`) and selective reruns with `POST /jobs/{id}/rerun?status=failed`
- Structured extraction inside a Batch job via `css_extractor` and `autoparse`
- Signed webhook delivery (`signature: true`) with HMAC verification of the `run.completed` payload
- CSV-based job input via the presigned-upload-URL flow
- Recurring scheduled jobs, including pausing and replacing a schedule
- A plain `asyncio`/`aiohttp` scraper with retries and concurrency, included for a side-by-side complexity comparison

## Prerequisites

- Python 3.9+
- A Zenrows API key — sign up and grab one from [docs.zenrows.com](https://docs.zenrows.com/)
- Dependencies installed from `requirements.txt` (`requests`, `python-dotenv`, `beautifulsoup4`, `aiohttp`)

## Installation

1. Clone this repository:
   ```bash
   git clone <this-repo-url>
   cd large-scale-web-scraping-zenrows-batch
   ```
2. Create and activate a virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate   # Windows: venv\Scripts\activate
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Configuration

Copy the example env file and add your key:

```bash
cp .env.example .env
```

```
ZENROWS_API_KEY=your_api_key
```

`.env` is excluded via `.gitignore` — never commit a real key.

`05_webhook.py` also reads one optional variable, `WEBHOOK_URL`. If set, it points the webhook at your own receiver instead of creating a temporary one via the webhook.site API.

## Project structure

```
.
├── client.py                # Shared helper: auth, job submit/poll, results, reruns, webhooks, HMAC, CSV, scheduling
├── 01_cloudflare_target.py  # Cloudflare-protected target
├── 02_volume_run.py         # Volume run + cost estimator
├── 03_failure_and_rerun.py  # Failure handling + rerun
├── 04_extraction.py         # css_extractor / autoparse
├── 05_webhook.py            # Signed webhook delivery
├── 06_diy_comparison.py     # Plain asyncio/aiohttp comparison (no Zenrows)
├── 07_csv_upload.py         # CSV upload flow
├── 08_scheduling.py         # Scheduled jobs: create, pause, replace
├── requirements.txt
├── .env.example
└── .gitignore
```

Each script writes its raw request/response JSON to a local `results/` folder as it runs (git-ignored).

## How it works

Every example follows the same underlying shape:

```
build task list  →  submit job (POST /jobs)  →  poll until terminal (GET /jobs/{id})  →  collect results (GET /jobs/{id}/results)
```

`client.py` implements this once — auth headers, backoff polling, paginated result collection — and every numbered script calls into it rather than repeating the HTTP boilerplate.

## Running the project

Each script is standalone: `python <script_name>.py`. Run whichever matches what you want to see.

- **`01_cloudflare_target.py`** — reach for this to see Zenrows clear a Cloudflare-protected page and report which credit tier it landed on.
- **`02_volume_run.py`** — reach for this to submit a real multi-URL batch and compare estimated vs. actual credit spend.
- **`03_failure_and_rerun.py`** — reach for this to see per-task error handling and how to rerun just the failed tasks.
- **`04_extraction.py`** — reach for this to get structured data back from a Batch job instead of raw HTML.
- **`05_webhook.py`** — reach for this to capture and verify a signed `run.completed` webhook delivery.
- **`06_diy_comparison.py`** — reach for this to see the plain-Python equivalent of script 01, with no Zenrows involved.
- **`07_csv_upload.py`** — reach for this when your URL list lives in a CSV rather than inline in code.
- **`08_scheduling.py`** — reach for this to set up a recurring job and see how pausing/replacing a schedule works.

## Output

- Console output for every script: submission confirmation, polling progress, and a plain-language summary of the result (cleared/not cleared, stats, credits spent, etc.).
- Each script also saves the raw JSON it received from the API into `results/`, named by script number (e.g. `01_cloudflare_job_final.json`), so you can inspect the exact payloads.
- `01_cloudflare_target.py` additionally saves the downloaded page content as `results/01_cloudflare_content.html`.
- `07_csv_upload.py` additionally saves the CSV it built and uploaded as `results/07_csv_input.csv`.
- Scripts that submit jobs (`01`, `02`, `05`, `07`, `08`) spend real credits on your account.

## Technologies

- Python
- [Zenrows Batch API](https://docs.zenrows.com/batch/introduction)
- `requests`
- `python-dotenv`
- `beautifulsoup4`
- `aiohttp`

## Related article

**How to Run Large-Scale Web Scraping Jobs with Zenrows Batch**
[ARTICLE_URL PLACEHOLDER, fill in before push]
