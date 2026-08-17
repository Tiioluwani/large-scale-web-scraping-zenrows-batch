"""
Webhook delivery via Zenrows Batch.

Creates a temporary public receiver via the webhook.site API, attaches it
to a small closed batch job with signature: true, and captures the literal
run.completed delivery: the raw JSON body, the X-Signature header, and the
X-ZenRows-Event-Id header.

Note: signed webhooks (signature: true) require an active HMAC key for
your org. If none exists yet, this script creates one via
POST /hmac/keys/rotate before submitting - otherwise submission is
rejected with 400 webhook_signing_requires_active_key.

If you'd rather point this at your own receiver (e.g. an ngrok-tunneled
Flask endpoint), set WEBHOOK_URL in .env and this script will use it
directly instead of creating a webhook.site token - but it will then only
save the job/submit responses, since there's no webhook.site API to poll
for the raw delivery in that case; check your own receiver's logs.
"""
import os
import time

import requests

import client

WEBHOOK_SITE_API = "https://webhook.site"

GOOD_URLS = [
    "https://www.scrapingcourse.com/ecommerce/product/abominable-hoodie/",
    "https://www.scrapingcourse.com/ecommerce/product/adrienne-trek-jacket/",
    "https://www.scrapingcourse.com/ecommerce/product/aeon-capri/",
]


def create_webhook_site_token():
    resp = requests.post(f"{WEBHOOK_SITE_API}/token", json={}, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    token_id = data["uuid"]
    return token_id, f"{WEBHOOK_SITE_API}/{token_id}"


def fetch_webhook_requests(token_id):
    resp = requests.get(
        f"{WEBHOOK_SITE_API}/token/{token_id}/requests",
        params={"sorting": "newest"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json().get("data", [])


def wait_for_delivery(token_id, timeout=120, delay=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        deliveries = fetch_webhook_requests(token_id)
        if deliveries:
            return deliveries
        time.sleep(delay)
    return []


def get_header(headers, name):
    """webhook.site returns headers as {lowercase_name: [values] or value}."""
    v = headers.get(name.lower())
    if isinstance(v, list):
        return v[0] if v else None
    return v


def ensure_active_hmac_key():
    """Signed webhooks (signature: true) need an active HMAC key for the
    org. Create one via POST /hmac/keys/rotate if none exists yet."""
    existing = client.list_hmac_keys()
    if existing.get("keys"):
        print(f"Existing HMAC keys: {existing['keys']}")
        return
    print("No HMAC key on file - creating one via POST /hmac/keys/rotate ...")
    created = client.rotate_hmac_key()
    # The secret is returned only once; keep it so signatures can be verified.
    client.save_json("05_hmac_key_created.json", created)
    print(f"Created HMAC key kid={created.get('kid')} (secret saved locally, not printed)")


def main():
    manual_webhook_url = os.environ.get("WEBHOOK_URL")
    token_id = None

    ensure_active_hmac_key()

    if manual_webhook_url:
        webhook_url = manual_webhook_url
        print(f"Using WEBHOOK_URL from .env: {webhook_url}")
    else:
        print("Creating a temporary webhook.site receiver ...")
        token_id, webhook_url = create_webhook_site_token()
        print(f"Webhook URL: {webhook_url}")
        client.save_json("05_webhook_endpoint.json", {"token_id": token_id, "url": webhook_url})

    payload = {
        "type": "regular",
        "status": "closed",
        "zenrows_params": {"mode": "auto"},
        "tasks": [{"url": u, "external_id": f"good-{i}"} for i, u in enumerate(GOOD_URLS, start=1)],
        "webhook": {"url": webhook_url, "signature": True},
    }

    print("\nSubmitting job with webhook attached (signature: true) ...")
    submitted = client.submit_job(payload)
    client.save_json("05_submit_response.json", submitted)
    job_id = submitted["job_id"]
    print(f"job_id={job_id}")

    job = client.wait_for_job(job_id)
    client.save_json("05_job_final.json", job)
    print(f"Run finished: {job['latest_run']['stats']}")

    if not token_id:
        print("\nNo webhook.site token to poll - check your own receiver's logs for the delivery.")
        return

    print("\nWaiting for webhook delivery on webhook.site ...")
    deliveries = wait_for_delivery(token_id)
    if not deliveries:
        print(f"No webhook delivery captured within the timeout. Check manually at: {webhook_url}")
        return

    delivery = deliveries[0]
    client.save_json("05_webhook_delivery_raw.json", delivery)

    headers = delivery.get("headers", {}) or {}
    x_signature = get_header(headers, "X-Signature")
    x_event_id = get_header(headers, "X-ZenRows-Event-Id")
    body = delivery.get("content")

    print(f"\nX-Signature: {x_signature}")
    print(f"X-ZenRows-Event-Id: {x_event_id}")
    print(f"Raw body:\n{body}")

    client.save_json(
        "05_webhook_summary.json",
        {"x_signature": x_signature, "x_zenrows_event_id": x_event_id, "body": body},
    )


if __name__ == "__main__":
    main()
