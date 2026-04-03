import json
import os
import socket
import time
from pathlib import Path

import httpx

CP_BASE = os.getenv("CP_BASE", "http://localhost:8000").rstrip("/")
WORKER_ID = os.getenv("WORKER_ID", f"{socket.gethostname()}:{os.getpid()}")
POLL_SECONDS = float(os.getenv("POLL_SECONDS", "1.5"))
TENANT_ID = os.getenv("TENANT_ID")
HEARTBEAT_SECONDS = float(os.getenv("HEARTBEAT_SECONDS", "10"))
SIMULATE_SECONDS = float(os.getenv("SIMULATE_SECONDS", "0.5"))

# Backoff delays in seconds for complete_run retries (max 5 attempts)
COMPLETE_RETRY_DELAYS = [0.5, 1.0, 2.0, 4.0, 8.0]

LOG_SOURCE = "data-plane-worker"
DEFAULT_FIXTURE = "inventory_mock_v1.json"
INVENTORY_PAGE_LIMIT = 500
TOP_DELTA_LIMIT = 15
SKU_SAMPLE_LIMIT = 8


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


def _fixtures_dir() -> Path:
    return Path(__file__).resolve().parent / "fixtures"


def _resolve_safe_fixture_path(fixtures_dir: Path, filename: str) -> Path:
    """Resolve a fixture filename to a path under fixtures_dir; reject traversal and invalid names."""
    if not isinstance(filename, str):
        raise ValueError("fixture name must be a string")
    name = filename.strip()
    if not name:
        raise ValueError("fixture name cannot be empty")
    p = Path(name)
    if p.name != name or p.parts != (name,):
        raise ValueError(
            "fixture name must be a single file name (no path separators or parent segments); "
            f"got {filename!r}"
        )
    fixtures_dir = fixtures_dir.resolve()
    candidate = (fixtures_dir / name).resolve()
    try:
        candidate.relative_to(fixtures_dir)
    except ValueError:
        raise ValueError("fixture path escapes fixtures directory") from None
    if not candidate.is_file():
        raise ValueError(f"fixture file not found: {name}")
    return candidate


def _validate_inventory_dag_spec(dag_spec: dict) -> None:
    """Fail fast on invalid provider config for inventory_snapshot_v0."""
    prov = dag_spec.get("provider")
    if prov is not None and not isinstance(prov, dict):
        raise ValueError("inventory_snapshot_v0 requires dag_spec.provider to be an object when set")
    provider_cfg = prov or {}
    provider_type = provider_cfg.get("type") or "mock"
    if provider_type != "mock":
        raise ValueError(
            f"inventory_snapshot_v0 only supports provider.type='mock'; got {provider_type!r}"
        )
    fx = provider_cfg.get("fixture")
    if fx is not None and not isinstance(fx, str):
        raise ValueError("dag_spec.provider.fixture must be a string when set")


def _fixture_name_for_run(dag_spec: dict, parameters: dict) -> str:
    """Return fixture filename: parameters.fixture overrides dag_spec.provider.fixture then default."""
    if "fixture" in parameters:
        ov = parameters["fixture"]
        if ov is None:
            raise ValueError("parameters.fixture cannot be null; omit the key to use the pipeline default")
        if not isinstance(ov, str):
            raise ValueError(
                "parameters.fixture must be a string (e.g. inventory_mock_v2.json); "
                f"got {type(ov).__name__}"
            )
        return ov.strip() or (_invalid_empty_fixture())
    provider_cfg = dag_spec.get("provider") or {}
    return provider_cfg.get("fixture") or DEFAULT_FIXTURE


def _invalid_empty_fixture() -> str:
    raise ValueError("parameters.fixture cannot be empty; omit the key to use the pipeline default")


def _load_inventory_fixture(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _fetch_canonical_inventory_for_facility(
    client: httpx.Client,
    facility_id: str,
    tenant_id: str,
) -> list[dict]:
    """Fetch all canonical rows for a facility with tenant scoping (paginated)."""
    out: list[dict] = []
    offset = 0
    while True:
        r = client.get(
            f"{CP_BASE}/api/inventory/items",
            params={
                "facility_id": facility_id,
                "tenant_id": tenant_id,
                "limit": INVENTORY_PAGE_LIMIT,
                "offset": offset,
            },
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        batch = data.get("items") or []
        out.extend(batch)
        total = int(data.get("count") or 0)
        offset += len(batch)
        if offset >= total or len(batch) == 0:
            break
    return out


def _row_to_qty(row: dict) -> tuple[int, int | None, int | None]:
    oh = int(row.get("on_hand") or 0)
    av = row.get("available")
    rs = row.get("reserved")
    return (
        oh,
        int(av) if av is not None else None,
        int(rs) if rs is not None else None,
    )


def _triples_equal(
    a: tuple[int, int | None, int | None],
    b: tuple[int, int | None, int | None],
) -> bool:
    return a == b


def _compute_inventory_delta(
    previous_by_sku: dict[str, tuple[int, int | None, int | None]],
    new_by_sku: dict[str, tuple[int, int | None, int | None]],
) -> dict:
    """Compare previous canonical state to the new snapshot; returns delta payload fields."""
    prev_skus = set(previous_by_sku.keys())
    new_skus = set(new_by_sku.keys())
    new_only = new_skus - prev_skus
    removed = prev_skus - new_skus
    both = prev_skus & new_skus

    unchanged = 0
    changed_any = 0
    qty_on_hand_changed = 0
    new_out_of_stock: list[str] = []
    back_in_stock: list[str] = []
    top_deltas: list[dict] = []

    total_on_hand_previous = sum(previous_by_sku[s][0] for s in prev_skus)
    total_on_hand_current = sum(new_by_sku[s][0] for s in new_skus)

    for sku in both:
        p = previous_by_sku[sku]
        c = new_by_sku[sku]
        if _triples_equal(p, c):
            unchanged += 1
        else:
            changed_any += 1
        if p[0] != c[0]:
            qty_on_hand_changed += 1
        prev_oh, cur_oh = p[0], c[0]
        if prev_oh > 0 and cur_oh == 0:
            if len(new_out_of_stock) < SKU_SAMPLE_LIMIT:
                new_out_of_stock.append(sku)
        if prev_oh == 0 and cur_oh > 0:
            if len(back_in_stock) < SKU_SAMPLE_LIMIT:
                back_in_stock.append(sku)
        d = cur_oh - prev_oh
        if d != 0:
            top_deltas.append(
                {
                    "sku": sku,
                    "previous_on_hand": prev_oh,
                    "current_on_hand": cur_oh,
                    "delta_on_hand": d,
                }
            )

    for sku in sorted(new_only):
        c = new_by_sku[sku]
        cur_oh = c[0]
        top_deltas.append(
            {
                "sku": sku,
                "previous_on_hand": 0,
                "current_on_hand": cur_oh,
                "delta_on_hand": cur_oh,
            }
        )

    for sku in sorted(removed):
        p = previous_by_sku[sku]
        prev_oh = p[0]
        top_deltas.append(
            {
                "sku": sku,
                "previous_on_hand": prev_oh,
                "current_on_hand": 0,
                "delta_on_hand": -prev_oh,
            }
        )

    top_deltas.sort(key=lambda x: abs(x["delta_on_hand"]), reverse=True)
    top_deltas = top_deltas[:TOP_DELTA_LIMIT]

    return {
        "changed_skus_count": changed_any,
        "unchanged_skus_count": unchanged,
        "new_skus_count": len(new_only),
        "removed_skus_count": len(removed),
        "removed_skus_sample": sorted(removed)[:SKU_SAMPLE_LIMIT],
        "new_out_of_stock_skus": new_out_of_stock,
        "back_in_stock_skus": back_in_stock,
        "quantity_changed_skus_count": qty_on_hand_changed,
        "top_deltas": top_deltas,
        "total_on_hand_previous": total_on_hand_previous,
        "total_on_hand_current": total_on_hand_current,
        "total_on_hand_delta": total_on_hand_current - total_on_hand_previous,
    }


def _execute_inventory_snapshot_v0(
    client: httpx.Client,
    run_id: str,
    dag_spec: dict,
    parameters: dict,
    tenant_id: str,
) -> None:
    """Execute the inventory_snapshot_v0 pipeline using a mock fixture and CP APIs."""
    print(f"[worker] inventory_snapshot_v0 parameters type={type(parameters).__name__} value={parameters!r}")
    _validate_inventory_dag_spec(dag_spec)

    facility_id = parameters.get("facility_id")
    if not facility_id or not isinstance(facility_id, str):
        raise ValueError(
            "inventory_snapshot_v0 requires parameters.facility_id (non-empty string UUID for the facility)"
        )

    provider_cfg = dag_spec.get("provider") or {}
    provider_type = provider_cfg.get("type") or "mock"
    mapping_version = dag_spec.get("mapping_version") or "mock_v1"

    fixture_name = _fixture_name_for_run(dag_spec, parameters)
    fixtures_dir = _fixtures_dir()
    append_log(
        client,
        run_id,
        "Validating fixture selection for inventory snapshot",
        source=LOG_SOURCE,
        meta={"pipeline_default": provider_cfg.get("fixture") or DEFAULT_FIXTURE, "resolved": fixture_name},
    )
    try:
        fixture_path = _resolve_safe_fixture_path(fixtures_dir, fixture_name)
    except ValueError as e:
        append_log(
            client,
            f"Fixture validation failed: {e}",
            level="ERROR",
            source=LOG_SOURCE,
            meta={"stage": "validate_fixture"},
        )
        raise

    append_log(
        client,
        run_id,
        "Starting inventory_snapshot_v0",
        source=LOG_SOURCE,
        meta={
            "facility_id": facility_id,
            "tenant_id": tenant_id,
            "provider": provider_type,
            "fixture": fixture_name,
            "fixture_path": fixture_path.name,
        },
    )

    append_log(
        client,
        run_id,
        "Loading inventory fixture from disk",
        source=LOG_SOURCE,
        meta={"fixture": fixture_name},
    )
    try:
        fixture = _load_inventory_fixture(fixture_path)
    except OSError as e:
        append_log(
            client,
            run_id,
            f"Failed to read fixture file: {e}",
            level="ERROR",
            source=LOG_SOURCE,
            meta={"stage": "load_fixture"},
        )
        raise
    as_of = fixture.get("as_of")

    append_log(
        client,
        run_id,
        "Fetching previous canonical inventory for facility",
        source=LOG_SOURCE,
        meta={"facility_id": facility_id},
    )
    try:
        prev_rows = _fetch_canonical_inventory_for_facility(client, facility_id, tenant_id)
    except Exception as e:
        append_log(
            client,
            run_id,
            f"Failed to fetch canonical inventory: {e}",
            level="ERROR",
            source=LOG_SOURCE,
            meta={"stage": "fetch_previous_canonical"},
        )
        raise
    previous_by_sku = {r["sku"]: _row_to_qty(r) for r in prev_rows if r.get("sku")}

    append_log(
        client,
        run_id,
        "Writing raw ingest payload",
        source=LOG_SOURCE,
        meta={"facility_id": facility_id},
    )
    raw_body = {
        "facility_id": facility_id,
        "provider": provider_type,
        "mapping_version": mapping_version,
        "as_of": as_of,
        "payload": fixture,
    }
    r_raw = client.post(f"{CP_BASE}/api/runs/{run_id}/raw-ingests", json=raw_body, timeout=10)
    r_raw.raise_for_status()

    # Step: MAP CANONICAL
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
        "Mapping raw snapshot rows to canonical inventory items",
        source=LOG_SOURCE,
        meta={"mapped_items": len(canonical_items)},
    )

    new_by_sku = {
        c["sku"]: (c["on_hand"], c["available"], c["reserved"]) for c in canonical_items
    }

    append_log(
        client,
        run_id,
        "Computing inventory deltas vs previous canonical state",
        source=LOG_SOURCE,
        meta={"previous_skus": len(previous_by_sku), "new_skus": len(new_by_sku)},
    )
    delta_block = _compute_inventory_delta(previous_by_sku, new_by_sku)

    append_log(
        client,
        run_id,
        "Upserting canonical inventory items",
        source=LOG_SOURCE,
        meta={"items_count": len(canonical_items)},
    )
    upsert_body = {
        "facility_id": facility_id,
        "source_provider": provider_type,
        "source_run_id": run_id,
        "as_of": as_of,
        "items": canonical_items,
    }
    try:
        r_upsert = client.post(f"{CP_BASE}/api/inventory/items:upsert", json=upsert_body, timeout=20)
        r_upsert.raise_for_status()
    except Exception as e:
        append_log(
            client,
            run_id,
            f"Canonical upsert failed: {e}",
            level="ERROR",
            source=LOG_SOURCE,
            meta={"stage": "upsert_canonical"},
        )
        raise
    upsert_data = r_upsert.json()

    # Summary artifact
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
        "schema_version": 1,
        "facility_id": facility_id,
        "tenant_id": tenant_id,
        "provider": provider_type,
        "mapping_version": mapping_version,
        "as_of": as_of,
        "fixture_used": fixture_name,
        "items_total": items_total,
        "out_of_stock": out_of_stock,
        "out_of_stock_skus_sample": out_of_stock_skus,
        "upserted": upsert_data.get("upserted"),
        "delta": delta_block,
    }

    append_log(
        client,
        run_id,
        "Writing inventory summary artifact",
        source=LOG_SOURCE,
        meta={"artifact_type": summary_artifact_type},
    )
    try:
        r_art = client.post(
            f"{CP_BASE}/api/runs/{run_id}/artifacts",
            json={"artifact_type": summary_artifact_type, "payload": summary_payload, "source": LOG_SOURCE},
            timeout=10,
        )
        r_art.raise_for_status()
    except Exception as e:
        append_log(
            client,
            run_id,
            f"Artifact write failed: {e}",
            level="ERROR",
            source=LOG_SOURCE,
            meta={"stage": "write_summary_artifact"},
        )
        raise

    append_log(
        client,
        run_id,
        "inventory_snapshot_v0 workflow completed",
        source=LOG_SOURCE,
        meta={"items_total": items_total, "fixture": fixture_name},
    )


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
            tenant_id = run.get("tenant_id")
            if not tenant_id:
                append_log(
                    client,
                    run_id,
                    "Run missing tenant_id; cannot execute",
                    level="ERROR",
                    source="worker",
                    meta={"status": "FAILED"},
                )
                complete_run(client, run_id, "FAILED", error_message="run missing tenant_id")
                continue

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
                        source=LOG_SOURCE,
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
                    _execute_inventory_snapshot_v0(client, run_id, dag_spec, params, tenant_id)
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
