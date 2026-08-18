"""
Resilient, reattachable safety monitor for a Zenrows Batch job.

A polling loop like the one in 10_scale_run.py is a single Python process
sitting between a large job and its safety cap - if that process dies
(network blip, machine restart, anything), the job keeps running on
Zenrows' side completely unsupervised. This script hardens that loop:
every API call is wrapped so that connection-level errors (DNS, timeout,
reset) are retried with backoff instead of crashing the process. Only a
real HTTP error response from the API (ZenrowsAPIError) is allowed to
propagate.

It's also reattachable: pass an existing job_id as the first CLI argument
to resume watching a job that's already running (e.g. after the original
monitor process died), or run it with no arguments to submit a fresh
large job and monitor it from the start.

Same safety contract as 10_scale_run.py: poll with gradual backoff, and
the moment latest_run.stats.spend.credits crosses SAFETY_CREDIT_CAP, call
POST /jobs/{id}/stop immediately (also retried through transient network
failures) and report.

Usage:
    python 11_scale_monitor.py                  # submit a new job, then monitor it
    python 11_scale_monitor.py <existing_job_id> # reattach and monitor only
"""
import sys
import time

import requests

import client

TOTAL_TASKS = 100_000
SAFETY_CREDIT_CAP = 300_000
POLL_TIMEOUT = 21600  # 6 hours from this script's start
INITIAL_DELAY = 2.0
MAX_DELAY = 15.0
NETWORK_RETRY_DELAY = 5.0
NETWORK_RETRY_MAX_DELAY = 30.0

# Small pool of real product pages, cycled out to TOTAL_TASKS tasks when
# this script submits its own job (no existing job_id given).
PRODUCT_URL_POOL = [
    "https://www.scrapingcourse.com/ecommerce/product/abominable-hoodie/",
    "https://www.scrapingcourse.com/ecommerce/product/adrienne-trek-jacket/",
    "https://www.scrapingcourse.com/ecommerce/product/aeon-capri/",
    "https://www.scrapingcourse.com/ecommerce/product/aero-daily-fitness-tee/",
    "https://www.scrapingcourse.com/ecommerce/product/aether-gym-pant/",
    "https://www.scrapingcourse.com/ecommerce/product/affirm-water-bottle/",
    "https://www.scrapingcourse.com/ecommerce/product/aim-analog-watch/",
    "https://www.scrapingcourse.com/ecommerce/product/ajax-full-zip-sweatshirt/",
    "https://www.scrapingcourse.com/ecommerce/product/ana-running-short/",
]


def build_tasks(total_tasks, pool):
    return [
        {"url": pool[i % len(pool)], "external_id": f"scale-{i + 1}"}
        for i in range(total_tasks)
    ]


def submit_new_job():
    tasks = build_tasks(TOTAL_TASKS, PRODUCT_URL_POOL)
    payload = {
        "type": "regular",
        "status": "closed",
        "zenrows_params": {"mode": "auto"},
        "tasks": tasks,
    }
    submitted = client.submit_job(payload)
    client.save_json("11_scale_monitor_submit_response.json", submitted)
    job_id = submitted["job_id"]
    print(f"Submitted new job: job_id={job_id} initial status={submitted['latest_run']['status']}")
    return job_id


def resilient_get_job(job_id):
    """GET /jobs/{id}, retrying forever on connection-level failures
    (DNS, timeout, reset). Only a real API error response raises."""
    delay = NETWORK_RETRY_DELAY
    while True:
        try:
            return client.get_job(job_id)
        except requests.exceptions.RequestException as e:
            print(f"  !! network error on get_job, retrying in {delay:.0f}s: {e}")
            time.sleep(delay)
            delay = min(delay * 1.5, NETWORK_RETRY_MAX_DELAY)


def resilient_stop_job(job_id, max_attempts=10):
    """POST /jobs/{id}/stop, retrying on connection-level failures. This
    call is safety-critical, so retry aggressively before giving up."""
    delay = NETWORK_RETRY_DELAY
    for attempt in range(1, max_attempts + 1):
        try:
            return client.stop_job(job_id)
        except requests.exceptions.RequestException as e:
            print(f"  !! network error on stop_job (attempt {attempt}/{max_attempts}), retrying in {delay:.0f}s: {e}")
            time.sleep(delay)
            delay = min(delay * 1.5, NETWORK_RETRY_MAX_DELAY)
    raise RuntimeError(f"stop_job failed after {max_attempts} attempts - could not confirm the job was stopped")


def main():
    if len(sys.argv) > 1:
        job_id = sys.argv[1]
        print(f"Reattaching safety monitor to existing job_id={job_id}")
    else:
        print("No job_id given - submitting a new job to monitor.")
        job_id = submit_new_job()

    started = time.time()
    deadline = started + POLL_TIMEOUT
    delay = INITIAL_DELAY
    stopped_for_safety = False
    poll_count = 0

    print(f"Safety cap: {SAFETY_CREDIT_CAP} credits. Timeout from now: {POLL_TIMEOUT}s.\n")

    while True:
        job = resilient_get_job(job_id)
        run = job["latest_run"]
        stats = run.get("stats", {})
        spend = stats.get("spend", {}) or {}
        credits = spend.get("credits", 0)
        completed = stats.get("completed", 0)
        total = stats.get("total", 0)
        elapsed = time.time() - started
        poll_count += 1

        progress = {
            "poll_count": poll_count,
            "elapsed_seconds": round(elapsed, 1),
            "run_status": run.get("status"),
            "completed": completed,
            "total": total,
            "successful": stats.get("successful"),
            "failed": stats.get("failed"),
            "credits_spent": credits,
            "cost": spend.get("cost"),
        }
        client.save_json("11_scale_monitor_progress.json", progress)
        print(
            f"  [{elapsed / 60:.1f}m] poll #{poll_count}: status={run.get('status')} "
            f"completed={completed}/{total} credits={credits}/{SAFETY_CREDIT_CAP}"
        )

        if credits >= SAFETY_CREDIT_CAP:
            print(f"\n!!! SAFETY CAP HIT: {credits} credits >= {SAFETY_CREDIT_CAP}. Calling POST /jobs/{{id}}/stop now. !!!")
            resilient_stop_job(job_id)
            stopped_for_safety = True
            time.sleep(2)
            job = resilient_get_job(job_id)
            break

        if run.get("status") in client.TERMINAL_STATUSES:
            break

        if time.time() > deadline:
            print(f"\n!!! TIMEOUT: {POLL_TIMEOUT}s elapsed without reaching a terminal state. !!!")
            break

        time.sleep(delay)
        delay = min(delay * 1.5, MAX_DELAY)

    elapsed = time.time() - started
    client.save_json("11_scale_monitor_job_final.json", job)

    final_run = job["latest_run"]
    final_stats = final_run.get("stats", {})
    final_spend = final_stats.get("spend", {}) or {}

    failed_sample = None
    if final_stats.get("failed", 0) > 0:
        try:
            failed_page = client.list_results(job_id, status="failed")
            client.save_json("11_scale_monitor_failed_sample.json", failed_page)
            failed_sample = failed_page.get("results", [])[:20]
        except client.ZenrowsAPIError as e:
            print(f"  (could not fetch failed-result sample: {e})")

    summary = {
        "job_id": job_id,
        "stopped_for_safety": stopped_for_safety,
        "final_run_status": final_run.get("status"),
        "elapsed_seconds_this_monitor": round(elapsed, 1),
        "stats": final_stats,
        "failure_reasons": final_stats.get("failure_reasons"),
        "failed_sample_external_ids": [r.get("external_id") for r in failed_sample] if failed_sample else [],
    }
    client.save_json("11_scale_monitor_results_summary.json", summary)

    print("\n=== FINAL REPORT (this monitor) ===")
    if stopped_for_safety:
        print(f"Job STOPPED EARLY for safety: credits crossed {SAFETY_CREDIT_CAP}.")
    else:
        print(f"Job finished naturally (status={final_run.get('status')}), never hit the {SAFETY_CREDIT_CAP}-credit cap.")
    print(f"Final stats: {final_stats}")
    print(f"Total spend: {final_spend}")


if __name__ == "__main__":
    main()
