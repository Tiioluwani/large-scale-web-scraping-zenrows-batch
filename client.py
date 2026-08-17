"""
Shared HTTP client and helpers for the Zenrows Batch API example scripts.

Loads ZENROWS_API_KEY from a .env file (see .env.example), wraps the
Batch REST API (https://docs.zenrows.com/batch/developer-guide-restapi),
and provides small utilities the individual numbered scripts share: job
submission, polling, paginated result collection, reruns, webhook
management, the client-side cost estimator, and result persistence to
results/.
"""
import json
import os
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://async.api.zenrows.com/v1"
API_KEY = os.environ.get("ZENROWS_API_KEY")

RESULTS_DIR = Path(__file__).parent / "results"

# GET /jobs/{id}: poll latest_run.status until it reaches one of these.
TERMINAL_STATUSES = {"completed", "stopped", "deleted"}


class ZenrowsAPIError(Exception):
    """Raised for any non-2xx response. Wraps the RFC 7807 problem body
    ({type, title, status, detail, code, invalid_tasks?})."""

    def __init__(self, status_code, problem):
        self.status_code = status_code
        self.problem = problem if isinstance(problem, dict) else {}
        self.code = self.problem.get("code")
        self.detail = self.problem.get("detail")
        super().__init__(f"HTTP {status_code} {self.code}: {self.detail}")


def _check_api_key():
    if not API_KEY:
        raise RuntimeError(
            "ZENROWS_API_KEY is not set. Copy .env.example to .env and add "
            "your key before running any of the numbered example scripts."
        )


def _headers(extra=None):
    _check_api_key()
    headers = {"X-API-Key": API_KEY}
    if extra:
        headers.update(extra)
    return headers


def _raise_for_status(response):
    if response.ok:
        return
    try:
        problem = response.json()
    except ValueError:
        problem = {"detail": response.text}
    raise ZenrowsAPIError(response.status_code, problem)


# --- Job lifecycle -----------------------------------------------------

def submit_job(payload, idempotency_key=None):
    """POST /jobs - create a closed or open job."""
    headers = _headers({"Content-Type": "application/json"})
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    resp = requests.post(f"{BASE_URL}/jobs", headers=headers, json=payload)
    _raise_for_status(resp)
    return resp.json()


def get_job(job_id):
    """GET /jobs/{job_id} - job + latest_run.status/stats."""
    resp = requests.get(f"{BASE_URL}/jobs/{job_id}", headers=_headers())
    _raise_for_status(resp)
    return resp.json()


def wait_for_job(job_id, timeout=900, initial_delay=2.0, max_delay=15.0, on_poll=None):
    """Poll GET /jobs/{id} with gradual backoff until latest_run.status is
    terminal (completed, stopped, deleted). Returns the final job object."""
    deadline = time.time() + timeout
    delay = initial_delay
    while True:
        job = get_job(job_id)
        run = job.get("latest_run") or {}
        if on_poll:
            on_poll(job)
        if run.get("status") in TERMINAL_STATUSES:
            return job
        if time.time() > deadline:
            raise TimeoutError(f"Timed out waiting for job {job_id} to reach a terminal state")
        time.sleep(delay)
        delay = min(delay * 1.5, max_delay)


# --- Results -------------------------------------------------------------

def list_results(job_id, status="all", cursor=None):
    """GET /jobs/{job_id}/results - one page of result rows."""
    params = {"status": status}
    if cursor:
        params["cursor"] = cursor
    resp = requests.get(f"{BASE_URL}/jobs/{job_id}/results", headers=_headers(), params=params)
    _raise_for_status(resp)
    return resp.json()


def iter_results(job_id, status="all"):
    """Yield every result row across all pages (follows next_cursor)."""
    cursor = None
    while True:
        page = list_results(job_id, status=status, cursor=cursor)
        for row in page.get("results", []):
            yield row
        cursor = page.get("next_cursor")
        if not cursor:
            break


def get_task_content(job_id, task_id):
    """GET /jobs/{job_id}/tasks/{task_id}/content.
    200 = content, 409 = still processing, 422 = failed (body is the error)."""
    resp = requests.get(f"{BASE_URL}/jobs/{job_id}/tasks/{task_id}/content", headers=_headers())
    return resp.status_code, resp


def download_result(result_url):
    """Fetch a presigned result_url (valid ~2h). Not authenticated with X-API-Key."""
    resp = requests.get(result_url)
    resp.raise_for_status()
    return resp


# --- Control endpoints -----------------------------------------------------

def rerun_job(job_id, status=None):
    """POST /jobs/{job_id}/rerun[?status=failed[,pending]].
    Response includes retried_tasks, inherited_tasks, latest_run."""
    params = {"status": status} if status else None
    resp = requests.post(f"{BASE_URL}/jobs/{job_id}/rerun", headers=_headers(), params=params)
    _raise_for_status(resp)
    return resp.json()


def set_webhook(job_id, url, signature=True):
    """PUT /jobs/{job_id}/webhook - set or replace the job's webhook."""
    resp = requests.put(
        f"{BASE_URL}/jobs/{job_id}/webhook",
        headers=_headers({"Content-Type": "application/json"}),
        json={"url": url, "signature": signature},
    )
    _raise_for_status(resp)
    return resp.json() if resp.content else None


def delete_webhook(job_id):
    """DELETE /jobs/{job_id}/webhook - stop deliveries."""
    resp = requests.delete(f"{BASE_URL}/jobs/{job_id}/webhook", headers=_headers())
    _raise_for_status(resp)


def create_csv_input_slot(fields, header=True):
    """POST /job_inputs (type=csv) - create a presigned CSV upload slot.
    fields maps canonical names ('url' required, 'external_id' optional)
    to your CSV's column headers (or 0-based indices if header=False)."""
    resp = requests.post(
        f"{BASE_URL}/job_inputs",
        headers=_headers({"Content-Type": "application/json"}),
        json={"type": "csv", "csv": {"header": header, "fields": fields}},
    )
    _raise_for_status(resp)
    return resp.json()


def upload_csv(slot, csv_bytes):
    """PUT the CSV bytes to the slot's presigned URL using the EXACT
    headers the slot specifies."""
    upload = slot["upload"]
    resp = requests.request(
        upload.get("method", "PUT"),
        upload["url"],
        headers=upload.get("headers", {}),
        data=csv_bytes,
    )
    resp.raise_for_status()
    return resp


def set_schedule_state(job_id, state):
    """POST /jobs/{id}/schedule/state - {"schedule_state": "paused"|"active"}."""
    resp = requests.post(
        f"{BASE_URL}/jobs/{job_id}/schedule/state",
        headers=_headers({"Content-Type": "application/json"}),
        json={"schedule_state": state},
    )
    _raise_for_status(resp)
    return resp.json() if resp.content else None


def replace_schedule(job_id, schedule):
    """PUT /jobs/{id}/schedule - replace the schedule config entirely."""
    resp = requests.put(
        f"{BASE_URL}/jobs/{job_id}/schedule",
        headers=_headers({"Content-Type": "application/json"}),
        json=schedule,
    )
    _raise_for_status(resp)
    return resp.json() if resp.content else None


def stop_job(job_id):
    """POST /jobs/{id}/stop - terminate the current run (terminal: stopped)."""
    resp = requests.post(f"{BASE_URL}/jobs/{job_id}/stop", headers=_headers())
    _raise_for_status(resp)
    return resp.json() if resp.content else None


def rotate_hmac_key():
    """POST /hmac/keys/rotate - creates the first active key, or stages a
    candidate if one is already active. The secret is returned only once."""
    resp = requests.post(f"{BASE_URL}/hmac/keys/rotate", headers=_headers())
    _raise_for_status(resp)
    return resp.json()


def finalize_hmac_key_rotation():
    """POST /hmac/keys/rotate/finalize - promote the staged candidate."""
    resp = requests.post(f"{BASE_URL}/hmac/keys/rotate/finalize", headers=_headers())
    _raise_for_status(resp)
    return resp.json() if resp.content else None


def list_hmac_keys():
    """GET /hmac/keys - key metadata only, never secrets."""
    resp = requests.get(f"{BASE_URL}/hmac/keys", headers=_headers())
    _raise_for_status(resp)
    return resp.json()


def probe_webhook(url, signature=True):
    """POST /webhook/test - verify a receiver before wiring it to a job."""
    resp = requests.post(
        f"{BASE_URL}/webhook/test",
        headers=_headers({"Content-Type": "application/json"}),
        json={"url": url, "signature": signature},
    )
    _raise_for_status(resp)
    return resp.json()


# --- Result persistence -----------------------------------------------------

def save_json(name, data):
    """Write data as pretty JSON to results/<name>."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / name
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def save_text(name, text):
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / name
    path.write_text(text, encoding="utf-8")
    return path


def save_bytes(name, data):
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESULTS_DIR / name
    path.write_bytes(data)
    return path


# --- Client-side cost estimator -----------------------------------------
# Mirrors the "Estimate cost" formula from the developer guide:
# https://docs.zenrows.com/batch/developer-guide-restapi#6-cost
# Tiers (credits per successful request): base=1, js_render=5,
# premium_proxy=10, both=25, mode=auto=1..25 (dynamic).

def _task_cost(params):
    if str(params.get("mode")) == "auto":
        return (1, 25)
    js = str(params.get("js_render")) == "true"
    proxy = str(params.get("premium_proxy")) == "true"
    c = 25 if js and proxy else 10 if proxy else 5 if js else 1
    return (c, c)


def estimate_cost(submit_body):
    """Sum the per-task credit range across a submit body's tasks, merging
    job-level zenrows_params with each task's own overrides."""
    job_params = submit_body.get("zenrows_params", {})
    tasks = submit_body.get("tasks", [])
    lo = hi = 0
    for t in tasks:
        merged = {**job_params, **t.get("zenrows_params", {})}
        a, b = _task_cost(merged)
        lo += a
        hi += b
    return {"tasks": len(tasks), "min": lo, "max": hi, "exact": lo == hi}
