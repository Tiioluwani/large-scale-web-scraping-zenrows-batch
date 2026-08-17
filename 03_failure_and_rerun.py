"""
Failure handling and reruns via Zenrows Batch.

Submits a job mixing known-good URLs with a few that fail at scrape time
(NXDOMAIN, a real 404, and an unroutable IP literal), inspects the failed
rows' error.code / error.detail once the run is terminal, then reruns just
the failures with POST /jobs/{id}/rerun?status=failed and checks the
response's retried_tasks / inherited_tasks against the good/broken split.

Note on malformed URLs: a syntactically malformed URL (no scheme, e.g.
"not-a-valid-url") does NOT become a per-task failed row. It causes the
whole POST /jobs call to be rejected synchronously with 400
invalid_argument and an invalid_tasks[] array - no job is created, so
there's nothing to poll or rerun. This script demonstrates that explicitly
in a preflight check before running the main failure/rerun flow, since it's
easy to assume malformed input behaves like any other failure.
"""
import client

GOOD_URLS = [
    "https://www.scrapingcourse.com/ecommerce/product/abominable-hoodie/",
    "https://www.scrapingcourse.com/ecommerce/product/adrienne-trek-jacket/",
    "https://www.scrapingcourse.com/ecommerce/product/aeon-capri/",
    "https://www.scrapingcourse.com/ecommerce/product/artemis-running-short/",
    "https://www.scrapingcourse.com/ecommerce/product/aero-daily-fitness-tee/",
]

# Syntactically valid, but fail at scrape time -> real `failed` result rows.
BROKEN_URLS = [
    "https://this-domain-should-not-exist-zenrows-example-9f31a2.com/",
    "https://www.scrapingcourse.com/ecommerce/product/this-product-does-not-exist-404/",
    "https://192.0.2.1/",  # RFC 5737 TEST-NET-1: guaranteed unroutable, times out
]

# Syntactically invalid -> rejects the whole submission (see preflight check).
MALFORMED_URL = "not-a-valid-url"


def build_tasks(urls, prefix):
    return [{"url": u, "external_id": f"{prefix}-{i}"} for i, u in enumerate(urls, start=1)]


def preflight_malformed_url_check():
    """Demonstrate that mixing in a malformed URL rejects the entire job at
    submission, rather than producing a per-task failure. Captures the real
    error instead of silently working around it."""
    print("=== Preflight: submitting a job that includes a malformed URL ===")
    payload = {
        "type": "regular",
        "status": "closed",
        "zenrows_params": {"mode": "auto"},
        "tasks": [
            {"url": GOOD_URLS[0], "external_id": "good-1"},
            {"url": MALFORMED_URL, "external_id": "malformed-1"},
        ],
    }
    try:
        resp = client.submit_job(payload)
        client.save_json("03_preflight_malformed_submit_response.json", resp)
        print("UNEXPECTED: submission succeeded despite the malformed URL.")
        print(resp)
    except client.ZenrowsAPIError as e:
        print(f"Submission rejected as expected: HTTP {e.status_code} code={e.code}")
        print(f"detail={e.detail}")
        print(f"invalid_tasks={e.problem.get('invalid_tasks')}")
        client.save_json("03_preflight_malformed_error.json", e.problem)


def main():
    preflight_malformed_url_check()

    tasks = build_tasks(GOOD_URLS, "good") + build_tasks(BROKEN_URLS, "broken")
    payload = {
        "type": "regular",
        "status": "closed",
        "zenrows_params": {"mode": "auto"},
        "tasks": tasks,
    }

    print(f"\n=== Main job: {len(GOOD_URLS)} good + {len(BROKEN_URLS)} scrape-time-broken URLs ===")
    submitted = client.submit_job(payload)
    client.save_json("03_submit_response.json", submitted)
    job_id = submitted["job_id"]
    print(f"job_id={job_id}")

    job = client.wait_for_job(job_id)
    client.save_json("03_job_final.json", job)
    stats = job["latest_run"]["stats"]
    print(f"Run finished: {stats}")

    results_page = client.list_results(job_id, status="all")
    client.save_json("03_results_all.json", results_page)

    failed_rows = [r for r in results_page["results"] if r["status"] == "failed"]
    print(f"\n{len(failed_rows)} failed task(s):")
    for row in failed_rows:
        err = row.get("error", {}) or {}
        print(f"  external_id={row.get('external_id')} url={row.get('url')}")
        print(f"    error.code={err.get('code')} error.detail={err.get('detail')}")

    expected_failed = len(BROKEN_URLS)
    expected_successful = len(GOOD_URLS)
    print(f"\nExpected failed={expected_failed}, actual failed={len(failed_rows)}")
    print(f"Expected successful={expected_successful}, actual successful={stats.get('successful')}")

    print("\nRerunning failed tasks: POST /jobs/{id}/rerun?status=failed ...")
    rerun_resp = client.rerun_job(job_id, status="failed")
    client.save_json("03_rerun_response.json", rerun_resp)
    print(f"Rerun response: {rerun_resp}")

    retried = rerun_resp.get("retried_tasks")
    inherited = rerun_resp.get("inherited_tasks")
    print(f"\nretried_tasks={retried} (expected {expected_failed})")
    print(f"inherited_tasks={inherited} (expected {expected_successful})")
    print(
        f"Match: retried={retried == expected_failed} "
        f"inherited={inherited == expected_successful}"
    )

    new_run = rerun_resp.get("latest_run") or {}
    new_run_id = new_run.get("run_id") or rerun_resp.get("run_id")
    if new_run_id:
        print(f"\nNew run_id: {new_run_id}")
        new_job = client.wait_for_job(job_id)
        client.save_json("03_rerun_job_final.json", new_job)
        print(f"Rerun finished: {new_job['latest_run']['stats']}")


if __name__ == "__main__":
    main()
