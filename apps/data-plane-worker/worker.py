import json
import os
import socket
import time

import httpx

CP_BASE = os.getenv("CP_BASE", "http://localhost:8000").rstrip("/")
WORKER_ID = os.getenv("WORKER_ID", f"{socket.gethostname()}:{os.getpid()}")
POLL_SECONDS = float(os.getenv("POLL_SECONDS", "1.5"))
TENANT_ID = os.getenv("TENANT_ID")
HEARTBEAT_SECONDS = float(os.getenv("HEARTBEAT_SECONDS", "10"))
SIMULATE_SECONDS = float(os.getenv("SIMULATE_SECONDS", "0.5"))

# Backoff delays in seconds for complete_run retries (max 5 attempts)
COMPLETE_RETRY_DELAYS = [0.5, 1.0, 2.0, 4.0, 8.0]


def append_log(
    client: httpx.Client,
    run_id: str,
    message: str,
    level: str = "INFO",
    source: str | None = "worker",
    meta: dict | None = None,
) -> None:
    """Append a log line to the control plane. Best-effort; does not raise."""
    try:
        payload = {"level": level, "message": message}
        if source is not None:
            payload["source"] = source
        if meta is not None:
            payload["meta"] = meta
        r = client.post(f"{CP_BASE}/api/runs/{run_id}/logs", json=payload, timeout=5)
        r.raise_for_status()
    except Exception as e:
        print(f"[worker] append_log failed: {e}")


def claim_run(client: httpx.Client):
    payload = {"worker_id": WORKER_ID}
    if TENANT_ID:
        payload["tenant_id"] = TENANT_ID

    r = client.post(f"{CP_BASE}/api/runs/claim", json=payload)
    r.raise_for_status()
    return r.json()


def send_heartbeat(client: httpx.Client, run_id: str) -> bool:
    """Send heartbeat for RUNNING run. Returns True to continue, False to stop (run no longer ours)."""
    try:
        r = client.post(
            f"{CP_BASE}/api/runs/{run_id}/heartbeat",
            json={"worker_id": WORKER_ID},
            timeout=5,
        )
        if r.status_code == 409:
            data = r.json() if r.content else {}
            reason = data.get("reason", "")
            if reason == "not_running":
                return False
            if reason == "worker_mismatch":
                print(f"[worker] heartbeat 409 worker_mismatch (claimed_by={data.get('claimed_by')}); stopping")
                return False
        return True
    except Exception:
        return True


def complete_run(client: httpx.Client, run_id: str, status: str, error_message: str | None = None):
    """Call POST /api/runs/{id}/complete with retries and backoff. On 409 (invalid state), returns None."""
    payload = {"status": status, "error_message": error_message}
    last_exc = None
    for attempt, delay in enumerate(COMPLETE_RETRY_DELAYS):
        try:
            r = client.post(f"{CP_BASE}/api/runs/{run_id}/complete", json=payload, timeout=15)
            if r.status_code == 409:
                print(f"[worker] complete skipped: run {run_id} is no longer RUNNING (cancelled or already terminal)")
                return None
            r.raise_for_status()
            return r.json()
        except httpx.HTTPStatusError as e:
            last_exc = e
            if e.response.status_code == 409:
                print(f"[worker] complete skipped: run {run_id} is no longer RUNNING (cancelled or already terminal)")
                return None
            if attempt < len(COMPLETE_RETRY_DELAYS) - 1:
                time.sleep(delay)
                continue
            raise
        except (httpx.RequestError, OSError) as e:
            last_exc = e
            if attempt < len(COMPLETE_RETRY_DELAYS) - 1:
                time.sleep(delay)
                continue
            raise
    if last_exc:
        raise last_exc
    return None


def _load_mock_inventory_fixture(name: str) -> dict:
    """Load a mock inventory JSON fixture from the local fixtures directory."""
    base_dir = os.path.dirname(__file__)
    fixtures_dir = os.path.join(base_dir, "fixtures")
    path = os.path.join(fixtures_dir, name)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _execute_inventory_snapshot_v0(
    client: httpx.Client,
    run_id: str,
    dag_spec: dict,
    parameters: dict,
) -> None:
    """Execute the inventory_snapshot_v0 pipeline using a mock fixture and CP APIs."""
    print(f"[worker] inventory_snapshot_v0 parameters type={type(parameters).__name__} value={parameters!r}")
    facility_id = parameters.get("facility_id")
    if not facility_id or not isinstance(facility_id, str):
        raise ValueError("inventory_snapshot_v0 requires parameters.facility_id")

    provider_cfg = dag_spec.get("provider") or {}
    provider_type = provider_cfg.get("type") or "mock"
    if provider_type != "mock":
        raise ValueError(f"inventory_snapshot_v0 only supports provider.type='mock', got {provider_type!r}")
    fixture_name = provider_cfg.get("fixture") or "inventory_mock_v1.json"
    mapping_version = dag_spec.get("mapping_version") or "mock_v1"

    append_log(
        client,
        run_id,
        "Starting inventory_snapshot_v0",
        source="worker",
        meta={"facility_id": facility_id, "provider": provider_type, "fixture": fixture_name},
    )

    # Step 1: FETCH (mock)
    append_log(client, run_id, "inventory_snapshot_v0: loading mock fixture", source="worker")
    fixture = _load_mock_inventory_fixture(fixture_name)
    as_of = fixture.get("as_of")

    # Step 2: STORE RAW
    append_log(client, run_id, "inventory_snapshot_v0: storing raw ingest", source="worker")
    raw_body = {
        "facility_id": facility_id,
        "provider": provider_type,
        "mapping_version": mapping_version,
        "as_of": as_of,
        "payload": fixture,
    }
    r_raw = client.post(f"{CP_BASE}/api/runs/{run_id}/raw-ingests", json=raw_body, timeout=10)
    r_raw.raise_for_status()

    # Step 3: MAP CANONICAL
    items = fixture.get("items") or []
    canonical_items = []
    for item in items:
        sku = item.get("sku")
        if not sku or not isinstance(sku, str):
            continue
        on_hand = int(item.get("on_hand") or 0)
        available = item.get("available")
        reserved = item.get("reserved")
        canonical_items.append(
            {
                "sku": sku,
                "on_hand": on_hand,
                "available": int(available) if available is not None else None,
                "reserved": int(reserved) if reserved is not None else None,
                "source_ref": None,
            }
        )

    append_log(
        client,
        run_id,
        "inventory_snapshot_v0: upserting canonical items",
        source="worker",
        meta={"items_count": len(canonical_items)},
    )
    upsert_body = {
        "facility_id": facility_id,
        "source_provider": provider_type,
        "source_run_id": run_id,
        "as_of": as_of,
        "items": canonical_items,
    }
    r_upsert = client.post(f"{CP_BASE}/api/inventory/items:upsert", json=upsert_body, timeout=20)
    r_upsert.raise_for_status()
    upsert_data = r_upsert.json()

    # Step 4: EMIT SUMMARY ARTIFACT
    items_total = len(canonical_items)
    out_of_stock_skus: list[str] = []
    out_of_stock = 0
    for c in canonical_items:
        available_val = c["available"]
        on_hand_val = c["on_hand"]
        is_oos = (available_val is not None and available_val <= 0) or (
            available_val is None and on_hand_val <= 0
        )
        if is_oos:
            out_of_stock += 1
            if len(out_of_stock_skus) < 10:
                out_of_stock_skus.append(c["sku"])

    summary_artifact_type = dag_spec.get("summary_artifact_type") or "inventory_summary"
    summary_payload = {
        "facility_id": facility_id,
        "provider": provider_type,
        "as_of": as_of,
        "items_total": items_total,
        "out_of_stock": out_of_stock,
        "out_of_stock_skus_sample": out_of_stock_skus,
        "upserted": upsert_data.get("upserted"),
    }
    append_log(
        client,
        run_id,
        "inventory_snapshot_v0: writing summary artifact",
        source="worker",
        meta={"artifact_type": summary_artifact_type},
    )
    r_art = client.post(
        f"{CP_BASE}/api/runs/{run_id}/artifacts",
        json={"artifact_type": summary_artifact_type, "payload": summary_payload, "source": "data-plane-worker"},
        timeout=10,
    )
    r_art.raise_for_status()


def main():
    with httpx.Client(timeout=10) as client:
        while True:
            claim = claim_run(client)
            if not claim.get("claimed"):
                print("No queued runs. Sleeping...")
                time.sleep(POLL_SECONDS)
                continue

            run = claim["run"]
            pipeline_version = claim["pipeline_version"]
            run_id = run["id"]
            append_log(client, run_id, f"Claimed run {run_id}", source="worker", meta={"run_id": run_id})
            print(f"Claimed run {run_id} -> RUNNING")

            try:
                print(f"[worker] claim keys: {list(claim.keys())}")
                dag_spec = pipeline_version.get("dag_spec")
                if dag_spec is None:
                    raise ValueError("pipeline_version.dag_spec is required")

                append_log(client, run_id, "Run began executing", source="worker", meta={"step": "execute"})

                if isinstance(dag_spec, dict) and dag_spec.get("kind") == "inventory_snapshot_v0":
                    append_log(
                        client,
                        run_id,
                        "Executing inventory_snapshot_v0 pipeline",
                        source="worker",
                        meta={"kind": "inventory_snapshot_v0"},
                    )
                    params = run.get("parameters") or {}
                    if isinstance(params, str):
                        try:
                            params = json.loads(params)
                        except json.JSONDecodeError:
                            params = {}
                    if not isinstance(params, dict):
                        params = {}
                    _execute_inventory_snapshot_v0(client, run_id, dag_spec, params)
                else:
                    append_log(client, run_id, "Simulate work started", source="worker", meta={"step": "simulate"})
                    # Simulate work with periodic heartbeats
                    end_time = time.monotonic() + SIMULATE_SECONDS
                    last_heartbeat = time.monotonic()
                    stopped_early = False
                    while time.monotonic() < end_time:
                        time.sleep(0.5)
                        if time.monotonic() - last_heartbeat >= HEARTBEAT_SECONDS:
                            if not send_heartbeat(client, run_id):
                                print(f"[worker] Run {run_id} no longer RUNNING; skipping completion")
                                stopped_early = True
                                break
                            last_heartbeat = time.monotonic()

                    if stopped_early:
                        continue

                    append_log(client, run_id, "Simulate work finished", source="worker", meta={"step": "simulate"})

                out = complete_run(client, run_id, "SUCCEEDED")
                if out is None:
                    print(f"Run {run_id} was cancelled or already terminal; skipping completion")
                else:
                    append_log(client, run_id, "Run completed successfully", source="worker", meta={"status": "SUCCEEDED"})
                    print(f"Completed run {run_id} -> {out['run']['status']}")
            except Exception as e:
                append_log(
                    client,
                    run_id,
                    f"Run failed: {e}",
                    level="ERROR",
                    source="worker",
                    meta={"error": str(e), "status": "FAILED"},
                )
                out = complete_run(client, run_id, "FAILED", error_message=str(e))
                if out is None:
                    print(f"Run {run_id} was cancelled or already terminal; could not mark FAILED")
                else:
                    print(f"Run {run_id} failed -> {out['run']['status']} ({e})")


if __name__ == "__main__":
    main()
