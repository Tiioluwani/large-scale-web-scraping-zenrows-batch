"""
Volume run via Zenrows Batch.

Paginates the real listing pages at scrapingcourse.com/ecommerce to collect
50-100 real product URLs, submits them as one closed batch job with
mode: "auto", polls to completion, and compares the client-side cost
estimator against the credits actually spent.
"""
import re
import time

import requests
from bs4 import BeautifulSoup

import client

LISTING_BASE = "https://www.scrapingcourse.com/ecommerce"
MIN_URLS = 50
MAX_URLS = 100
PRODUCT_LINK_RE = re.compile(r"^https://www\.scrapingcourse\.com/ecommerce/product/[^/]+/?$")


def collect_product_urls(min_urls=MIN_URLS, max_urls=MAX_URLS):
    urls = []
    seen = set()
    page = 1
    while len(urls) < max_urls:
        page_url = LISTING_BASE + "/" if page == 1 else f"{LISTING_BASE}/page/{page}/"
        resp = requests.get(page_url, timeout=30)
        if resp.status_code == 404:
            break
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        found_this_page = 0
        for a in soup.select("a[href]"):
            href = a["href"]
            if href.startswith("/"):
                href = "https://www.scrapingcourse.com" + href
            if PRODUCT_LINK_RE.match(href) and href not in seen:
                seen.add(href)
                urls.append(href)
                found_this_page += 1
                if len(urls) >= max_urls:
                    break

        print(f"  page {page}: {found_this_page} new product URL(s) (total {len(urls)})")
        if found_this_page == 0:
            break
        page += 1

    return urls[:max_urls]


def main():
    print("Collecting product URLs from the ecommerce listing pages ...")
    urls = collect_product_urls()
    print(f"Collected {len(urls)} product URLs")
    if len(urls) < MIN_URLS:
        print(f"WARNING: collected fewer than {MIN_URLS} URLs; continuing anyway.")

    client.save_json("02_volume_collected_urls.json", {"count": len(urls), "urls": urls})

    payload = {
        "type": "regular",
        "status": "closed",
        "zenrows_params": {"mode": "auto"},
        "tasks": [{"url": u, "external_id": f"product-{i}"} for i, u in enumerate(urls, start=1)],
    }

    estimate = client.estimate_cost(payload)
    print(f"\nClient-side cost estimate: {estimate}")
    client.save_json("02_volume_estimate.json", estimate)

    print(f"\nSubmitting job with {len(urls)} tasks ...")
    started = time.time()
    submitted = client.submit_job(payload)
    client.save_json("02_volume_submit_response.json", submitted)
    job_id = submitted["job_id"]
    print(f"job_id={job_id}")

    def on_poll(job):
        s = job["latest_run"]["stats"]
        print(f"  polling: status={job['latest_run']['status']} completed={s.get('completed')}/{s.get('total')}")

    job = client.wait_for_job(job_id, timeout=1800, on_poll=on_poll)
    elapsed = time.time() - started
    client.save_json("02_volume_job_final.json", job)

    stats = job["latest_run"]["stats"]
    run_spend = stats.get("spend")

    print(f"\nRun finished in {elapsed:.1f}s")
    print(f"Stats: total={stats.get('total')} successful={stats.get('successful')} failed={stats.get('failed')}")
    print(f"Actual spend: {run_spend}")
    print(f"Estimate was: min={estimate['min']} max={estimate['max']} credits (exact={estimate['exact']})")
    if run_spend:
        actual_credits = run_spend.get("credits")
        print(f"\nEstimate vs actual -> estimated [{estimate['min']}, {estimate['max']}], actual {actual_credits}")


if __name__ == "__main__":
    main()
