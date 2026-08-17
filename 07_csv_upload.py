"""
CSV upload via Zenrows Batch.

Follows the docs' three-step flow for large inputs:
  1. POST /job_inputs (type=csv) - create a presigned upload slot.
  2. PUT the CSV to that presigned URL using the EXACT headers the slot
     specifies.
  3. POST /jobs referencing file_input_id instead of inline tasks.

Builds a small real CSV with a header row and an external_id column, to
confirm external_id round-trips through a file-based submission the same
way it does for inline tasks.
"""
import csv
import io
import json
from pathlib import Path

import client

RESULTS_DIR = Path(__file__).parent / "results"

# Known-good product pages on the ecommerce demo store.
KNOWN_GOOD_URLS = [
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


def build_csv(urls):
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["URL", "Customer Ref"])
    for i, u in enumerate(urls, start=1):
        writer.writerow([u, f"csv-{i}"])
    return buf.getvalue().encode("utf-8")


def main():
    urls = KNOWN_GOOD_URLS
    print(f"Using {len(urls)} known-good URLs")

    csv_bytes = build_csv(urls)
    (RESULTS_DIR / "07_csv_input.csv").parent.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / "07_csv_input.csv").write_bytes(csv_bytes)
    print(f"Built CSV ({len(csv_bytes)} bytes), saved to results/07_csv_input.csv")

    print("\n=== Step 1: POST /job_inputs (create upload slot) ===")
    slot = client.create_csv_input_slot(fields={"url": "URL", "external_id": "Customer Ref"}, header=True)
    client.save_json("07_csv_slot_response.json", slot)
    print(json.dumps(slot, indent=2))

    upload_headers = slot.get("upload", {}).get("headers", {})
    print(f"\nExact headers required by the presigned URL: {upload_headers}")

    print("\n=== Step 2: PUT the CSV to the presigned URL ===")
    upload_resp = client.upload_csv(slot, csv_bytes)
    print(f"Upload response status: {upload_resp.status_code}")
    client.save_json(
        "07_csv_upload_response.json",
        {"status_code": upload_resp.status_code, "headers_used": upload_headers, "response_headers": dict(upload_resp.headers)},
    )

    print("\n=== Step 3: POST /jobs referencing file_input_id ===")
    payload = {
        "type": "regular",
        "status": "closed",
        "file_input_id": slot["file_input_id"],
        "zenrows_params": {"mode": "auto"},
    }
    submitted = client.submit_job(payload)
    client.save_json("07_csv_submit_response.json", submitted)
    job_id = submitted["job_id"]
    print(f"job_id={job_id}")
    print(json.dumps(submitted, indent=2))

    def on_poll(job):
        s = job["latest_run"]["stats"]
        print(f"  polling: status={job['latest_run']['status']} completed={s.get('completed')}/{s.get('total')}")

    job = client.wait_for_job(job_id, timeout=300, on_poll=on_poll)
    client.save_json("07_csv_job_final.json", job)
    stats = job["latest_run"]["stats"]
    print(f"\nRun finished: {stats}")

    results_page = client.list_results(job_id, status="all")
    client.save_json("07_csv_results.json", results_page)

    expected_ids = {f"csv-{i}" for i in range(1, len(urls) + 1)}
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
    print(f"\nexternal_id round-trip: expected {sorted(expected_ids)}")
    print(f"external_id round-trip: got      {sorted(seen_ids)}")
    print(f"Missing: {sorted(missing) if missing else 'none'}")
    print(f"Unexpected: {sorted(unexpected) if unexpected else 'none'}")
    print(f"Round-trip clean: {not missing and not unexpected}")

    print(f"\nStats: {stats}")


if __name__ == "__main__":
    main()
