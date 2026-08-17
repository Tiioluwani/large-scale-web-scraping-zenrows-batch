"""
Cloudflare-protected target via Zenrows Batch.

Submits a closed job with mode: "auto" against a page behind Cloudflare's
managed challenge, polls GET /jobs/{id} to a terminal state, downloads the
result content, and checks it for the page's own bypass-confirmation text.
Prints whether it cleared, how long it took, and what credit tier it landed
on (the run's spend object).
"""
import time

import client

TARGET_URL = "https://www.scrapingcourse.com/cloudflare-challenge"

# The exact wording on a given challenge page can vary, so check a few
# plausible variants and also surface the raw text around "bypass" so the
# real confirmation string can be read off directly from the run.
CANDIDATE_PHRASES = [
    "you bypassed the cloudflare challenge",
    "bypassed the cloudflare challenge",
    "you bypassed the challenge",
]


def main():
    payload = {
        "type": "regular",
        "status": "closed",
        "zenrows_params": {"mode": "auto"},
        "tasks": [{"url": TARGET_URL, "external_id": "cloudflare-challenge"}],
    }

    print(f"Submitting job for {TARGET_URL} ...")
    started = time.time()
    submitted = client.submit_job(payload)
    client.save_json("01_cloudflare_submit_response.json", submitted)
    job_id = submitted["job_id"]
    print(f"job_id={job_id} initial status={submitted['latest_run']['status']}")

    job = client.wait_for_job(job_id)
    elapsed = time.time() - started
    client.save_json("01_cloudflare_job_final.json", job)

    stats = job["latest_run"]["stats"]
    run_status = job["latest_run"]["status"]
    print(f"Run finished: status={run_status} stats={stats} elapsed={elapsed:.1f}s")

    results_page = client.list_results(job_id, status="all")
    client.save_json("01_cloudflare_results.json", results_page)

    rows = results_page.get("results", [])
    if not rows:
        print("No result rows returned.")
        return

    row = rows[0]
    print(f"\nTask status: {row['status']}")
    if row.get("spend"):
        print(f"Task spend: {row['spend']}")

    if row["status"] != "successful":
        print(f"Task failed: {row.get('error')}")
        return

    content_resp = client.download_result(row["result_url"])
    body = content_resp.text
    client.save_text("01_cloudflare_content.html", body)

    lowered = body.lower()
    cleared = any(phrase in lowered for phrase in CANDIDATE_PHRASES)

    if not cleared and "bypass" in lowered:
        idx = lowered.find("bypass")
        print("\nFound 'bypass' but not a known exact phrase. Context:")
        print(body[max(0, idx - 80): idx + 120])

    print(f"\nCleared Cloudflare challenge: {cleared}")
    print(f"Time to terminal state: {elapsed:.1f}s")
    run_spend = job["latest_run"]["stats"].get("spend")
    print(f"Run-level spend (credit tier): {run_spend}")


if __name__ == "__main__":
    main()
