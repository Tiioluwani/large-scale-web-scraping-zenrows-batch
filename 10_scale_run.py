"""
Large-scale volume run via Zenrows Batch.

Cycles a small pool of real product URLs out to a large task list
(100,000 by default) and submits it as a single closed job with
mode: "auto", to see real throughput and real total spend at a scale far
beyond a normal volume run.

Real throughput and total spend at this scale aren't known ahead of time,
so this script:
  1. Confirms 0 active (pending/running) jobs before submitting - most
     accounts allow only a small number of concurrent jobs.
  2. Submits the large task list as one job.
  3. Polls with a long timeout (default 6 hours) using the same
     gradual-backoff pattern as client.wait_for_job, but with its own
     safety check: every poll inspects latest_run.stats.spend.credits,
     and if it crosses a configurable cap, immediately calls
     POST /jobs/{id}/stop and reports the job stopped early for safety
     with the exact spend/stats at that moment.
  4. If it finishes naturally under the cap, reports the real final stats.

Progress is written to results/10_scale_progress.json on every poll (not
just at the end) so the run can be inspected mid-flight. See
11_scale_monitor.py for a version of this polling loop hardened against
local network failures, which can also reattach to a job_id that's
already running.
"""
import json
import time

import client

TOTAL_TASKS = 100_000
SAFETY_CREDIT_CAP = 300_000
POLL_TIMEOUT = 21600  # 6 hours
INITIAL_DELAY = 2.0
MAX_DELAY = 15.0

# Small pool of real product pages, cycled out to TOTAL_TASKS tasks.
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


def check_no_active_jobs():
    print("=== Step 0: confirm 0 active jobs (GET /jobs) before submitting ===")
    listing = client.list_jobs()
    client.save_json("10_scale_active_jobs_check.json", listing)
    active = [
        j for j in listing.get("jobs", [])
        if (j.get("latest_run") or {}).get("status") in ("pending", "running")
    ]
    print(f"Jobs on first page: {len(listing.get('jobs', []))}; active (pending/running): {len(active)}")
    if active:
        print("Active jobs found:")
        for j in active:
            print(f"  job_id={j['job_id']} status={j['latest_run']['status']}")
    return active


def main():
    active = check_no_active_jobs()
    if active:
        print("\nABORTING: account already has active job(s) running.")
        print(f"Not submitting the {TOTAL_TASKS}-task job. Re-run once those clear.")
        return

    print("0 active jobs confirmed. Proceeding.\n")

    print(f"=== Step 1: build {TOTAL_TASKS} tasks by cycling a {len(PRODUCT_URL_POOL)}-URL pool ===")
    tasks = build_tasks(TOTAL_TASKS, PRODUCT_URL_POOL)
    payload = {
        "type": "regular",
        "status": "closed",
        "zenrows_params": {"mode": "auto"},
        "tasks": tasks,
    }

    estimate = client.estimate_cost(payload)
    print(f"Client-side cost estimate: {estimate}")
    client.save_json("10_scale_estimate.json", estimate)

    print(f"\n=== Step 2: submit job with {len(tasks)} tasks ===")
    started = time.time()
    submitted = client.submit_job(payload)
    client.save_json("10_scale_submit_response.json", submitted)
    job_id = submitted["job_id"]
    print(f"job_id={job_id} initial status={submitted['latest_run']['status']}")

    print(f"\n=== Step 3: poll to completion (timeout={POLL_TIMEOUT}s, safety cap={SAFETY_CREDIT_CAP} credits) ===")
    deadline = started + POLL_TIMEOUT
    delay = INITIAL_DELAY
    stopped_for_safety = False
    poll_count = 0

    while True:
        job = client.get_job(job_id)
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
        client.save_json("10_scale_progress.json", progress)
        print(
            f"  [{elapsed / 60:.1f}m] poll #{poll_count}: status={run.get('status')} "
            f"completed={completed}/{total} credits={credits}/{SAFETY_CREDIT_CAP}"
        )

        if credits >= SAFETY_CREDIT_CAP:
            print(f"\n!!! SAFETY CAP HIT: {credits} credits >= {SAFETY_CREDIT_CAP}. Calling POST /jobs/{{id}}/stop now. !!!")
            client.stop_job(job_id)
            stopped_for_safety = True
            time.sleep(2)
            job = client.get_job(job_id)
            break

        if run.get("status") in client.TERMINAL_STATUSES:
            break

        if time.time() > deadline:
            print(f"\n!!! TIMEOUT: {POLL_TIMEOUT}s elapsed without reaching a terminal state. !!!")
            break

        time.sleep(delay)
        delay = min(delay * 1.5, MAX_DELAY)

    elapsed = time.time() - started
    client.save_json("10_scale_job_final.json", job)

    final_run = job["latest_run"]
    final_stats = final_run.get("stats", {})
    final_spend = final_stats.get("spend", {}) or {}

    print(f"\n=== Step 4: results summary ===")
    failed_sample = None
    if final_stats.get("failed", 0) > 0:
        try:
            failed_page = client.list_results(job_id, status="failed")
            client.save_json("10_scale_failed_sample.json", failed_page)
            failed_sample = failed_page.get("results", [])[:20]
        except client.ZenrowsAPIError as e:
            print(f"  (could not fetch failed-result sample: {e})")

    summary = {
        "job_id": job_id,
        "stopped_for_safety": stopped_for_safety,
        "final_run_status": final_run.get("status"),
        "elapsed_seconds": round(elapsed, 1),
        "elapsed_human": f"{elapsed / 3600:.2f}h",
        "stats": final_stats,
        "failure_reasons": final_stats.get("failure_reasons"),
        "failed_sample_external_ids": [r.get("external_id") for r in failed_sample] if failed_sample else [],
    }
    client.save_json("10_scale_results_summary.json", summary)
    print(json.dumps(summary, indent=2))

    print("\n=== FINAL REPORT ===")
    if stopped_for_safety:
        print(f"Job STOPPED EARLY for safety: credits crossed {SAFETY_CREDIT_CAP}.")
    else:
        print(f"Job finished naturally (status={final_run.get('status')}), never hit the {SAFETY_CREDIT_CAP}-credit cap.")
    print(f"Total elapsed: {elapsed:.1f}s ({elapsed / 3600:.2f}h)")
    print(f"Final stats: {final_stats}")
    print(f"Total spend: {final_spend}")
    print(f"Successful/Failed split: {final_stats.get('successful')}/{final_stats.get('failed')} of {final_stats.get('total')}")


if __name__ == "__main__":
    main()
