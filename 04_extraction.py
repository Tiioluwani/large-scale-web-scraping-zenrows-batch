"""
Extraction inside Batch (css_extractor and autoparse).

Checks that css_extractor and autoparse work as job-level zenrows_params on
a Batch job (not just on a single Fetch request), against a couple of real
product pages on scrapingcourse.com/ecommerce, and records the actual
structured shape that comes back in the result content.
"""
import json

import client

PRODUCT_URLS = [
    "https://www.scrapingcourse.com/ecommerce/product/abominable-hoodie/",
    "https://www.scrapingcourse.com/ecommerce/product/adrienne-trek-jacket/",
]

# Best-guess selectors for this WooCommerce-style demo store. If a selector
# misses, the saved raw result still shows exactly what css_extractor
# returns for a miss (e.g. null/empty) - the point here is the actual
# response shape, not a guaranteed perfect match.
CSS_SELECTORS = {
    "title": "h1",
    "price": ".price",
    "description": ".woocommerce-product-details__short-description",
}

# css_extractor must be passed as a JSON-encoded STRING value in
# zenrows_params, not a native JSON object - sending an object is rejected
# with a 400.
CSS_EXTRACTOR_PARAM = json.dumps(CSS_SELECTORS)


def run_job(label, zenrows_params, filename_prefix):
    payload = {
        "type": "regular",
        "status": "closed",
        "zenrows_params": zenrows_params,
        "tasks": [
            {"url": u, "external_id": f"{filename_prefix}-{i}"}
            for i, u in enumerate(PRODUCT_URLS, start=1)
        ],
    }

    print(f"\n=== {label} ===")
    try:
        submitted = client.submit_job(payload)
    except client.ZenrowsAPIError as e:
        print(f"SUBMISSION FAILED: HTTP {e.status_code} code={e.code} detail={e.detail}")
        client.save_json(f"{filename_prefix}_submit_error.json", e.problem)
        return
    client.save_json(f"{filename_prefix}_submit_response.json", submitted)
    job_id = submitted["job_id"]
    print(f"job_id={job_id}")

    job = client.wait_for_job(job_id)
    client.save_json(f"{filename_prefix}_job_final.json", job)
    print(f"stats: {job['latest_run']['stats']}")

    results_page = client.list_results(job_id, status="all")
    client.save_json(f"{filename_prefix}_results.json", results_page)

    for row in results_page.get("results", []):
        print(f"\n  {row.get('external_id')}: status={row['status']}")
        if row["status"] != "successful":
            print(f"    error={row.get('error')}")
            continue

        content_resp = client.download_result(row["result_url"])
        content_type = content_resp.headers.get("content-type", "")
        ext = ".json" if "json" in content_type else ".txt"
        saved = client.save_bytes(f"{filename_prefix}_{row.get('external_id')}{ext}", content_resp.content)
        print(f"    content-type: {content_type}")
        print(f"    saved to: {saved}")
        print(f"    preview: {content_resp.text[:500]}")


def main():
    run_job(
        "css_extractor as job-level zenrows_params",
        {"mode": "auto", "css_extractor": CSS_EXTRACTOR_PARAM},
        "04_css",
    )
    run_job(
        "autoparse as job-level zenrows_params",
        {"mode": "auto", "autoparse": "true"},
        "04_autoparse",
    )


if __name__ == "__main__":
    main()
