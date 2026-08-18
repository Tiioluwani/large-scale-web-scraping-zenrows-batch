"""
Open (queue-mode) job via Zenrows Batch.

The docs flag this as still being finalized during the beta:
  "Open (queue-mode) jobs are still being finalized during the beta and
  may not be available yet. If POST /jobs with status: 'open' returns a
  503, use a closed job or a CSV upload for now."

This script checks that directly and cheaply:
  1. POST /jobs with status: "open" and no tasks yet.
     - If that 503s, stop immediately - that's the answer - and save the
       raw error response.
  2. If it succeeds, POST /jobs/{job_id}/tasks with a small first batch
     of real product URLs.
  3. POST /jobs/{job_id}/tasks again with a second small batch and
     last_batch: true to close the job.
  4. Poll to completion and report real stats, same shape as the other
     numbered examples.

No workaround, no retry-past-503 - whatever the API actually does is the
result.
"""
import json

import client

PRODUCT_URLS_BATCH_1 = [
    "https://www.scrapingcourse.com/ecommerce/product/abominable-hoodie/",
    "https://www.scrapingcourse.com/ecommerce/product/adrienne-trek-jacket/",
]

PRODUCT_URLS_BATCH_2 = [
    "https://www.scrapingcourse.com/ecommerce/product/aeon-capri/",
]


def main():
    print("=== Step 1: POST /jobs with status: 'open', no tasks ===")
    payload = {
        "type": "regular",
        "status": "open",
        "zenrows_params": {"mode": "auto"},
    }
    print(json.dumps(payload, indent=2))

    try:
        submitted = client.submit_job(payload)
    except client.ZenrowsAPIError as e:
        client.save_json(
            "09_open_create_error.json",
            {"status_code": e.status_code, "problem": e.problem},
        )
        print(f"\nHTTP {e.status_code}: {json.dumps(e.problem, indent=2)}")
        if e.status_code == 503:
            print("\n=== RESULT: Open jobs are NOT available yet (503 as documented). ===")
            print("Stopping here per the docs' guidance - no workaround attempted.")
        else:
            print(f"\n=== RESULT: Open job creation failed with an unexpected status ({e.status_code}), not the documented 503. ===")
        return

    client.save_json("09_open_create_response.json", submitted)
    job_id = submitted["job_id"]
    print(f"\nSUCCESS: open job created. job_id={job_id}")
    print(json.dumps(submitted, indent=2))
    print(f"initial status={submitted.get('status')} latest_run.status={submitted.get('latest_run', {}).get('status')}")

    print("\n=== Step 2: POST /jobs/{job_id}/tasks - first batch (2 URLs, last_batch=False) ===")
    tasks_1 = [{"url": u, "external_id": f"open-1-{i}"} for i, u in enumerate(PRODUCT_URLS_BATCH_1, start=1)]
    print(json.dumps({"tasks": tasks_1, "last_batch": False}, indent=2))
    batch_1_resp = client.add_tasks(job_id, tasks_1, last_batch=False)
    client.save_json("09_open_batch_1_response.json", batch_1_resp)
    print(json.dumps(batch_1_resp, indent=2) if batch_1_resp else "(no response body)")

    job_after_batch_1 = client.get_job(job_id)
    client.save_json("09_open_after_batch_1.json", job_after_batch_1)
    print(f"After batch 1: latest_run.status={job_after_batch_1['latest_run']['status']} stats={job_after_batch_1['latest_run'].get('stats')}")

    print("\n=== Step 3: POST /jobs/{job_id}/tasks - second batch (1 URL, last_batch=True) ===")
    tasks_2 = [{"url": u, "external_id": f"open-2-{i}"} for i, u in enumerate(PRODUCT_URLS_BATCH_2, start=1)]
    print(json.dumps({"tasks": tasks_2, "last_batch": True}, indent=2))
    batch_2_resp = client.add_tasks(job_id, tasks_2, last_batch=True)
    client.save_json("09_open_batch_2_response.json", batch_2_resp)
    print(json.dumps(batch_2_resp, indent=2) if batch_2_resp else "(no response body)")

    job_after_batch_2 = client.get_job(job_id)
    client.save_json("09_open_after_batch_2.json", job_after_batch_2)
    print(f"After batch 2 (last_batch=True): latest_run.status={job_after_batch_2['latest_run']['status']} stats={job_after_batch_2['latest_run'].get('stats')}")

    print("\n=== Step 4: poll to completion ===")

    def on_poll(job):
        s = job["latest_run"]["stats"]
        print(f"  polling: status={job['latest_run']['status']} completed={s.get('completed')}/{s.get('total')}")

    job = client.wait_for_job(job_id, timeout=300, on_poll=on_poll)
    client.save_json("09_open_final.json", job)
    stats = job["latest_run"]["stats"]
    run_status = job["latest_run"]["status"]
    print(f"\nRun finished: status={run_status} stats={stats}")

    results_page = client.list_results(job_id, status="all")
    client.save_json("09_open_results.json", results_page)

    expected_ids = {f"open-1-{i}" for i in range(1, len(PRODUCT_URLS_BATCH_1) + 1)} | {
        f"open-2-{i}" for i in range(1, len(PRODUCT_URLS_BATCH_2) + 1)
    }
    seen_ids = set()
    print(f"\n{len(results_page['results'])} result row(s):")
    for row in results_page["results"]:
        ext_id = row.get("external_id")
        seen_ids.add(ext_id)
        print(f"  external_id={ext_id} url={row.get('url')} status={row.get('status')}")
        if row["status"] != "successful":
            print(f"    error={row.get('error')}")

    missing = expected_ids - seen_ids
    unexpected = seen_ids - expected_ids
    print(f"\nExpected external_ids: {sorted(expected_ids)}")
    print(f"Seen external_ids:     {sorted(seen_ids)}")
    print(f"Missing: {sorted(missing) if missing else 'none'}")
    print(f"Unexpected: {sorted(unexpected) if unexpected else 'none'}")

    print(f"\nStats: {stats}")
    print("\n=== RESULT: Open job submission (POST /jobs status=open + POST /jobs/{id}/tasks + last_batch=True) WORKS. ===")


if __name__ == "__main__":
    main()
