"""
Scheduling via Zenrows Batch.

Creates a scheduled job (type: "scheduled") against 1-2 cheap product
pages, immediately inspects the schedule fields, then exercises pause and
schedule-replacement, and finally confirms the job is left in a paused
state so it cannot keep firing and spending credits after this script
exits.

Safety-first ordering: the schedule is paused via POST
/jobs/{id}/schedule/state IMMEDIATELY after creation, before any other
inspection happens, and the script re-confirms paused state as its very
last step (including re-pausing if the schedule replacement step turns out
to reactivate it). No zenrows_params are set on the tasks (plain base-tier
requests), so even an unexpected fire before the pause call lands is
minimal cost.

A paused scheduled job still exists in your account afterward - delete it
from the Zenrows dashboard if you want it gone entirely rather than just
paused.
"""
import json

import client

# Cheap, known-good, base-tier (no js_render/premium_proxy/mode) targets.
SCHEDULE_URLS = [
    "https://www.scrapingcourse.com/ecommerce/product/abominable-hoodie/",
    "https://www.scrapingcourse.com/ecommerce/product/adrienne-trek-jacket/",
]

INITIAL_SCHEDULE = {"rate": {"every": 24, "unit": "hour"}}
REPLACEMENT_SCHEDULE = {
    "calendar": {
        "times_of_day": ["09:00", "18:00"],
        "cadence": {"weekly": {"days": ["mon", "wed", "fri"]}},
    },
    "timezone": "Europe/Berlin",
}


def get_schedule_state(job):
    """Schedule state field name/location isn't confirmed until you see a
    real response - check the likely spots and report whatever is there."""
    return {
        "top_level_schedule_state": job.get("schedule_state"),
        "schedule_object": job.get("schedule"),
        "latest_run_present": job.get("latest_run") is not None,
        "latest_run_status": (job.get("latest_run") or {}).get("status"),
    }


def main():
    payload = {
        "type": "scheduled",
        "status": "closed",
        "schedule": INITIAL_SCHEDULE,
        "tasks": [{"url": u, "external_id": f"sched-{i}"} for i, u in enumerate(SCHEDULE_URLS, start=1)],
    }

    print("=== Creating scheduled job (rate: every 24 hours) ===")
    submitted = client.submit_job(payload)
    client.save_json("08_submit_response.json", submitted)
    job_id = submitted["job_id"]
    print(f"job_id={job_id}")
    print(json.dumps(submitted, indent=2))

    print("\n=== Inspecting schedule fields on the create response (no waiting) ===")
    create_state = get_schedule_state(submitted)
    print(json.dumps(create_state, indent=2))
    client.save_json("08_create_schedule_state.json", create_state)

    # Safety first: pause immediately, before doing anything else.
    print("\n=== SAFETY: pausing the schedule immediately ===")
    pause_resp = client.set_schedule_state(job_id, "paused")
    client.save_json("08_pause_response.json", pause_resp)
    print(json.dumps(pause_resp, indent=2) if pause_resp else "(empty response body)")

    job_after_pause = client.get_job(job_id)
    client.save_json("08_job_after_pause.json", job_after_pause)
    after_pause_state = get_schedule_state(job_after_pause)
    print(f"\nState after pause: {json.dumps(after_pause_state, indent=2)}")

    print("\n=== Replacing the schedule: PUT /jobs/{id}/schedule ===")
    replace_resp = client.replace_schedule(job_id, REPLACEMENT_SCHEDULE)
    client.save_json("08_replace_response.json", replace_resp)
    print(json.dumps(replace_resp, indent=2) if replace_resp else "(empty response body)")

    job_after_replace = client.get_job(job_id)
    client.save_json("08_job_after_replace.json", job_after_replace)
    after_replace_state = get_schedule_state(job_after_replace)
    print(f"\nState after replace: {json.dumps(after_replace_state, indent=2)}")

    replacement_stuck = job_after_replace.get("schedule") == REPLACEMENT_SCHEDULE
    print(f"Replacement schedule matches what was sent: {replacement_stuck}")
    if job_after_replace.get("schedule") != REPLACEMENT_SCHEDULE:
        print(f"  sent:     {REPLACEMENT_SCHEDULE}")
        print(f"  returned: {job_after_replace.get('schedule')}")

    # Some APIs reactivate a schedule on replace - check, and re-pause if so.
    still_paused = after_replace_state.get("top_level_schedule_state") == "paused"
    print(f"\nStill paused after replace: {still_paused}")
    if not still_paused:
        print("Replace reactivated the schedule - re-pausing now (cleanup safety).")
        client.set_schedule_state(job_id, "paused")

    print("\n=== FINAL SAFETY CHECK ===")
    final_job = client.get_job(job_id)
    client.save_json("08_job_final.json", final_job)
    final_state = get_schedule_state(final_job)
    print(json.dumps(final_state, indent=2))

    is_safe = final_state.get("top_level_schedule_state") == "paused"
    print(f"\nJob {job_id} left in a paused state: {is_safe}")
    if not is_safe:
        print("WARNING: could not confirm paused state via schedule_state field. "
              "Manually verify this job in the Zenrows dashboard before ending the session.")
        print(f"Full final job object: {json.dumps(final_job, indent=2)}")


if __name__ == "__main__":
    main()
