"""Shared logic for run-scoped inventory snapshots and run-to-run comparison (raw-ingest fixture as source)."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session


class InventorySnapshotError(Exception):
    def __init__(self, status_code: int, reason: str, message: str):
        self.status_code = status_code
        self.reason = reason
        self.message = message
        super().__init__(message)


def _iso(dt: Any) -> str | None:
    if dt is not None and hasattr(dt, "isoformat"):
        return dt.isoformat()
    return None


def payload_to_dict(payload: Any) -> dict | None:
    if payload is None:
        return None
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, str):
        try:
            out = json.loads(payload)
            return out if isinstance(out, dict) else None
        except json.JSONDecodeError:
            return None
    return None


def parse_parameters_facility_id(parameters: Any) -> str | None:
    if not parameters or not isinstance(parameters, dict):
        return None
    fid = parameters.get("facility_id")
    return fid if isinstance(fid, str) and fid.strip() else None


def is_oos(on_hand: int, available: int | None) -> bool:
    if available is not None:
        return available <= 0
    return on_hand <= 0


def dag_kind(dag_spec: Any) -> str | None:
    if not dag_spec or not isinstance(dag_spec, dict):
        return None
    k = dag_spec.get("kind")
    return k if isinstance(k, str) else None


def normalize_items_from_fixture_payload(payload: dict) -> list[dict[str, Any]]:
    items_in = payload.get("items")
    if not isinstance(items_in, list):
        return []
    out: list[dict[str, Any]] = []
    for item in items_in:
        if not isinstance(item, dict):
            continue
        sku = item.get("sku")
        if not sku or not isinstance(sku, str):
            continue
        on_hand = int(item.get("on_hand") or 0)
        av = item.get("available")
        rv = item.get("reserved")
        out.append(
            {
                "sku": sku,
                "on_hand": on_hand,
                "available": int(av) if av is not None else None,
                "reserved": int(rv) if rv is not None else None,
            }
        )
    return out


def fetch_run_with_version(db: Session, run_id: str) -> dict | None:
    row = db.execute(
        text(
            """
            SELECT r.id, r.tenant_id, r.pipeline_version_id, r.status, r.trigger_type, r.parameters,
                   r.created_at, r.finished_at,
                   pv.dag_spec
            FROM pipeline_runs r
            INNER JOIN pipeline_versions pv ON pv.id = r.pipeline_version_id
            WHERE r.id = :run_id
            """
        ),
        {"run_id": run_id},
    ).mappings().first()
    return dict(row) if row else None


def get_latest_raw_ingest(db: Session, run_id: str) -> dict | None:
    row = db.execute(
        text(
            """
            SELECT id, run_id, tenant_id, facility_id, provider, mapping_version, fetched_at, as_of, payload
            FROM pipeline_run_raw_ingests
            WHERE run_id = :run_id
            ORDER BY fetched_at DESC
            LIMIT 1
            """
        ),
        {"run_id": run_id},
    ).mappings().first()
    if not row:
        return None
    d = dict(row)
    for k in ("fetched_at", "as_of"):
        if d.get(k) is not None and hasattr(d[k], "isoformat"):
            d[k] = d[k].isoformat()
    return d


def get_latest_inventory_summary_payload(db: Session, run_id: str) -> dict | None:
    row = db.execute(
        text(
            """
            SELECT payload
            FROM pipeline_run_artifacts
            WHERE run_id = :run_id AND artifact_type = 'inventory_summary'
            ORDER BY created_at DESC
            LIMIT 1
            """
        ),
        {"run_id": run_id},
    ).mappings().first()
    if not row:
        return None
    return payload_to_dict(row["payload"])


def resolve_facility_id(parameters: Any, raw_row: dict | None) -> str | None:
    pf = parse_parameters_facility_id(parameters)
    if pf:
        return pf
    if raw_row and raw_row.get("facility_id"):
        return str(raw_row["facility_id"])
    return None


def compact_run_summary(
    run_id: str,
    status: str,
    created_at: Any,
    finished_at: Any,
    items: list[dict[str, Any]],
    artifact: dict | None,
) -> dict[str, Any]:
    oos = sum(1 for it in items if is_oos(it["on_hand"], it["available"]))
    out: dict[str, Any] = {
        "run_id": run_id,
        "status": status,
        "created_at": _iso(created_at),
        "finished_at": _iso(finished_at),
        "fixture_used": artifact.get("fixture_used") if artifact else None,
        "items_total": len(items),
        "out_of_stock": oos,
    }
    if artifact:
        if artifact.get("items_total") is not None:
            out["artifact_items_total"] = artifact.get("items_total")
        if artifact.get("out_of_stock") is not None:
            out["artifact_out_of_stock"] = artifact.get("out_of_stock")
    return out


def _parse_raw_payload(raw_row: dict) -> dict:
    payload = raw_row.get("payload")
    pl = payload_to_dict(payload)
    if not isinstance(pl, dict):
        raise InventorySnapshotError(
            422,
            "invalid_raw_payload",
            "Latest raw ingest payload is missing or not a JSON object.",
        )
    return pl


def build_run_inventory_snapshot(db: Session, run_id: str) -> dict[str, Any]:
    """Normalized snapshot from latest raw ingest fixture for an inventory_snapshot_v0 run."""
    ctx = fetch_run_with_version(db, run_id)
    if not ctx:
        raise InventorySnapshotError(404, "run_not_found", "Run not found.")
    if dag_kind(ctx.get("dag_spec")) != "inventory_snapshot_v0":
        raise InventorySnapshotError(
            400,
            "not_inventory_snapshot_run",
            "Run is not an inventory_snapshot_v0 pipeline.",
        )

    raw = get_latest_raw_ingest(db, run_id)
    if not raw:
        raise InventorySnapshotError(
            422,
            "missing_raw_ingest",
            "No raw ingest row for this run; snapshot comparison is not available.",
        )

    pl = _parse_raw_payload(raw)
    items = normalize_items_from_fixture_payload(pl)
    as_of = pl.get("as_of")
    if as_of is not None and not isinstance(as_of, str):
        as_of = str(as_of) if as_of is not None else None

    facility_id = resolve_facility_id(ctx.get("parameters"), raw)
    if not facility_id:
        raise InventorySnapshotError(
            422,
            "missing_facility_id",
            "Could not resolve facility_id from run parameters or raw ingest.",
        )

    art = get_latest_inventory_summary_payload(db, run_id)

    return {
        "run_id": run_id,
        "tenant_id": ctx["tenant_id"],
        "facility_id": facility_id,
        "status": ctx["status"],
        "created_at": _iso(ctx.get("created_at")),
        "finished_at": _iso(ctx.get("finished_at")),
        "provider": raw.get("provider"),
        "mapping_version": raw.get("mapping_version"),
        "as_of": as_of,
        "raw_ingest_id": raw.get("id"),
        "items": items,
        "count": len(items),
        "summary_artifact_present": art is not None,
    }


def _items_to_map(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {i["sku"]: dict(i) for i in items}


def _change_sort_key(ch: dict[str, Any]) -> int:
    kind = ch.get("change_kind")
    if kind == "removed_from_b":
        return abs(int(ch.get("on_hand_a") or 0))
    if kind == "new_in_b":
        return abs(int(ch.get("on_hand_b") or 0))
    return abs(int(ch.get("delta_on_hand") or 0))


def compute_run_comparison(
    items_a: list[dict[str, Any]],
    items_b: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    map_a = _items_to_map(items_a)
    map_b = _items_to_map(items_b)
    skus = set(map_a) | set(map_b)
    sku_changes: list[dict[str, Any]] = []
    counts = {
        "changed_skus_count": 0,
        "unchanged_skus_count": 0,
        "new_skus_count": 0,
        "removed_skus_count": 0,
        "new_out_of_stock_count": 0,
        "back_in_stock_count": 0,
    }
    total_on_hand_a = sum(x["on_hand"] for x in map_a.values())
    total_on_hand_b = sum(x["on_hand"] for x in map_b.values())

    for sku in skus:
        a = map_a.get(sku)
        b = map_b.get(sku)
        if a and not b:
            counts["removed_skus_count"] += 1
            sku_changes.append(
                {
                    "sku": sku,
                    "change_kind": "removed_from_b",
                    "on_hand_a": a["on_hand"],
                    "on_hand_b": None,
                    "available_a": a["available"],
                    "available_b": None,
                    "reserved_a": a["reserved"],
                    "reserved_b": None,
                    "delta_on_hand": -a["on_hand"],
                }
            )
        elif b and not a:
            counts["new_skus_count"] += 1
            sku_changes.append(
                {
                    "sku": sku,
                    "change_kind": "new_in_b",
                    "on_hand_a": None,
                    "on_hand_b": b["on_hand"],
                    "available_a": None,
                    "available_b": b["available"],
                    "reserved_a": None,
                    "reserved_b": b["reserved"],
                    "delta_on_hand": b["on_hand"],
                }
            )
        elif a and b:
            same = (
                a["on_hand"] == b["on_hand"]
                and a["available"] == b["available"]
                and a["reserved"] == b["reserved"]
            )
            if same:
                counts["unchanged_skus_count"] += 1
            else:
                counts["changed_skus_count"] += 1
                sku_changes.append(
                    {
                        "sku": sku,
                        "change_kind": "changed",
                        "on_hand_a": a["on_hand"],
                        "on_hand_b": b["on_hand"],
                        "available_a": a["available"],
                        "available_b": b["available"],
                        "reserved_a": a["reserved"],
                        "reserved_b": b["reserved"],
                        "delta_on_hand": b["on_hand"] - a["on_hand"],
                    }
                )
            oos_a = is_oos(a["on_hand"], a["available"])
            oos_b = is_oos(b["on_hand"], b["available"])
            if not oos_a and oos_b:
                counts["new_out_of_stock_count"] += 1
            if oos_a and not oos_b:
                counts["back_in_stock_count"] += 1

    sku_changes.sort(key=_change_sort_key, reverse=True)
    return sku_changes, {
        **counts,
        "total_on_hand_a": total_on_hand_a,
        "total_on_hand_b": total_on_hand_b,
        "total_on_hand_delta": total_on_hand_b - total_on_hand_a,
    }


MAX_SKU_CHANGES_RETURNED = 800


def compare_inventory_runs(db: Session, tenant_id: str, run_id_a: str, run_id_b: str) -> dict[str, Any]:
    if run_id_a == run_id_b:
        raise InventorySnapshotError(400, "same_run", "run_id_a and run_id_b must differ.")

    ctx_a = fetch_run_with_version(db, run_id_a)
    ctx_b = fetch_run_with_version(db, run_id_b)
    if not ctx_a:
        raise InventorySnapshotError(404, "run_not_found", f"Run not found: {run_id_a}")
    if not ctx_b:
        raise InventorySnapshotError(404, "run_not_found", f"Run not found: {run_id_b}")

    if ctx_a["tenant_id"] != tenant_id or ctx_b["tenant_id"] != tenant_id:
        raise InventorySnapshotError(400, "tenant_mismatch", "One or both runs do not belong to this tenant.")

    if dag_kind(ctx_a.get("dag_spec")) != "inventory_snapshot_v0":
        raise InventorySnapshotError(400, "not_inventory_snapshot_run", f"Run {run_id_a} is not inventory_snapshot_v0.")
    if dag_kind(ctx_b.get("dag_spec")) != "inventory_snapshot_v0":
        raise InventorySnapshotError(400, "not_inventory_snapshot_run", f"Run {run_id_b} is not inventory_snapshot_v0.")

    raw_a = get_latest_raw_ingest(db, run_id_a)
    raw_b = get_latest_raw_ingest(db, run_id_b)
    if not raw_a:
        raise InventorySnapshotError(
            422,
            "missing_raw_ingest",
            f"No raw ingest for run {run_id_a}; cannot compare historical snapshots.",
        )
    if not raw_b:
        raise InventorySnapshotError(
            422,
            "missing_raw_ingest",
            f"No raw ingest for run {run_id_b}; cannot compare historical snapshots.",
        )

    pl_a = _parse_raw_payload(raw_a)
    pl_b = _parse_raw_payload(raw_b)
    items_a = normalize_items_from_fixture_payload(pl_a)
    items_b = normalize_items_from_fixture_payload(pl_b)

    fac_a = resolve_facility_id(ctx_a.get("parameters"), raw_a)
    fac_b = resolve_facility_id(ctx_b.get("parameters"), raw_b)
    if not fac_a or not fac_b:
        raise InventorySnapshotError(
            422,
            "missing_facility_id",
            "Could not resolve facility_id for one or both runs.",
        )
    if fac_a != fac_b:
        raise InventorySnapshotError(
            400,
            "facility_mismatch",
            f"Runs target different facilities ({fac_a} vs {fac_b}).",
        )

    art_a = get_latest_inventory_summary_payload(db, run_id_a)
    art_b = get_latest_inventory_summary_payload(db, run_id_b)

    sku_changes, agg = compute_run_comparison(items_a, items_b)
    total_change_rows = len(sku_changes)
    truncated = total_change_rows > MAX_SKU_CHANGES_RETURNED
    sku_changes_out = sku_changes[:MAX_SKU_CHANGES_RETURNED]

    new_oos_skus_sample: list[str] = []
    bis_skus_sample: list[str] = []
    map_a = _items_to_map(items_a)
    map_b = _items_to_map(items_b)
    for sku in sorted(set(map_a) & set(map_b)):
        a, b = map_a[sku], map_b[sku]
        if not is_oos(a["on_hand"], a["available"]) and is_oos(b["on_hand"], b["available"]):
            if len(new_oos_skus_sample) < 15:
                new_oos_skus_sample.append(sku)
        if is_oos(a["on_hand"], a["available"]) and not is_oos(b["on_hand"], b["available"]):
            if len(bis_skus_sample) < 15:
                bis_skus_sample.append(sku)

    return {
        "tenant_id": tenant_id,
        "facility_id": fac_a,
        "run_id_a": run_id_a,
        "run_id_b": run_id_b,
        "summary_a": compact_run_summary(
            run_id_a,
            ctx_a["status"],
            ctx_a.get("created_at"),
            ctx_a.get("finished_at"),
            items_a,
            art_a,
        ),
        "summary_b": compact_run_summary(
            run_id_b,
            ctx_b["status"],
            ctx_b.get("created_at"),
            ctx_b.get("finished_at"),
            items_b,
            art_b,
        ),
        "changed_skus_count": agg["changed_skus_count"],
        "unchanged_skus_count": agg["unchanged_skus_count"],
        "new_skus_count": agg["new_skus_count"],
        "removed_skus_count": agg["removed_skus_count"],
        "new_out_of_stock_count": agg["new_out_of_stock_count"],
        "back_in_stock_count": agg["back_in_stock_count"],
        "total_on_hand_a": agg["total_on_hand_a"],
        "total_on_hand_b": agg["total_on_hand_b"],
        "total_on_hand_delta": agg["total_on_hand_delta"],
        "sku_changes": sku_changes_out,
        "sku_changes_total": total_change_rows,
        "sku_changes_truncated": truncated,
        "new_out_of_stock_skus_sample": new_oos_skus_sample,
        "back_in_stock_skus_sample": bis_skus_sample,
        "source": "raw_ingest_fixture_items",
    }
