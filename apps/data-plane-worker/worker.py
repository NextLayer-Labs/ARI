import time
import httpx

CONTROL_PLANE = "http://127.0.0.1:8000"
TENANT_ID = "580115b4-a291-4917-8dbd-247cfa13e2d6"

def claim_run(client: httpx.Client):
    r = client.post(f"{CONTROL_PLANE}/api/runs/claim", json={"tenant_id": TENANT_ID})
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json()

def complete_run(client: httpx.Client, run_id: str, status: str, error: str | None = None):
    payload = {"status": status, "error": error}
    r = client.post(f"{CONTROL_PLANE}/api/runs/{run_id}/complete", json=payload)
    r.raise_for_status()
    return r.json()

def main():
    with httpx.Client(timeout=10) as client:
        while True:
            run = claim_run(client)
            if not run:
                print("No queued runs. Sleeping...")
                time.sleep(2)
                continue

            run_id = run["id"]
            print(f"Claimed run {run_id} -> RUNNING")

            try:
                # Simulate work (later this becomes: execute dag_spec nodes)
                print("Simulating inventory_ingest...")
                time.sleep(3)

                out = complete_run(client, run_id, "SUCCEEDED")
                print(f"Completed run {run_id} -> {out['status']}")
            except Exception as e:
                out = complete_run(client, run_id, "FAILED", error=str(e))
                print(f"Run {run_id} failed -> {out['status']} ({e})")

if __name__ == "__main__":
    main()
