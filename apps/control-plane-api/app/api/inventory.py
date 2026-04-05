import json
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.schemas import InventoryItemsUpsertIn
from app.db.deps import get_db


router = APIRouter(prefix="/api/inventory", tags=["inventory"])


def _payload_to_dict(payload: Any) -> dict | None:
    if payload is None:
        return None
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, str):
        try:
            return json.loads(payload)
        except json.JSONDecodeError:
            return None
    return None


def _artifact_summary_for_history(payload: dict | None) -> dict[str, Any]:
    """Flatten inventory_summary artifact payload for facility history (partial data OK)."""
    out: dict[str, Any] = {
        "fixture_used": None,
        "items_total": None,
        "out_of_stock": None,
        "changed_skus_count": None,
        "new_skus_count": None,
        "back_in_stock_count": None,
        "new_out_of_stock_count": None,
        "top_deltas_sample": None,
        "artifact_present": False,
    }
    if not payload:
        return out
    out["artifact_present"] = True
    out["fixture_used"] = payload.get("fixture_used")
    out["items_total"] = payload.get("items_total")
    out["out_of_stock"] = payload.get("out_of_stock")
    delta = payload.get("delta")
    if isinstance(delta, dict):
        out["changed_skus_count"] = delta.get("changed_skus_count")
        out["new_skus_count"] = delta.get("new_skus_count")
        nos = delta.get("new_out_of_stock_skus")
        bis = delta.get("back_in_stock_skus")
        # Prefer explicit counts when present (forward-compatible); else sample list lengths.
        if isinstance(delta.get("new_out_of_stock_count"), int):
            out["new_out_of_stock_count"] = delta["new_out_of_stock_count"]
        elif isinstance(nos, list):
            out["new_out_of_stock_count"] = len(nos)
        if isinstance(delta.get("back_in_stock_count"), int):
            out["back_in_stock_count"] = delta["back_in_stock_count"]
        elif isinstance(bis, list):
            out["back_in_stock_count"] = len(bis)
        td = delta.get("top_deltas")
        if isinstance(td, list) and len(td) > 0:
            out["top_deltas_sample"] = td[:5]
    return out


def _get_run_tenant(db: Session, run_id: str) -> dict | None:
    """Return a minimal run row (id, tenant_id) for the given run_id, or None if not found."""
    row = db.execute(
        text("SELECT id, tenant_id FROM pipeline_runs WHERE id = :run_id"),
        {"run_id": run_id},
    ).mappings().first()
    return dict(row) if row else None


@router.post("/items:upsert")
def upsert_inventory_items(body: InventoryItemsUpsertIn, db: Session = Depends(get_db)):
    """Bulk upsert canonical inventory items for a facility, deriving tenant_id from source_run_id."""
    if not body.items or len(body.items) == 0:
        raise HTTPException(status_code=400, detail="items_required")
    if len(body.items) > 5000:
        raise HTTPException(status_code=400, detail="too_many_items")

    run = _get_run_tenant(db, body.source_run_id)
    if run is None:
        return JSONResponse(
            status_code=404,
            content={"ok": False, "reason": "run_not_found"},
        )
    tenant_id = run["tenant_id"]

    for item in body.items:
        if not item.sku or not isinstance(item.sku, str):
            raise HTTPException(status_code=400, detail="invalid_sku")

    as_of_value = body.as_of
    now_iso = datetime.utcnow().isoformat() + "Z"
    as_of_cast = as_of_value

    values_clause_parts = []
    params: dict = {
        "tenant_id": tenant_id,
        "facility_id": body.facility_id,
        "source_provider": body.source_provider,
        "source_run_id": body.source_run_id,
        "as_of": as_of_cast,
        "now_iso": now_iso,
    }
    for idx, item in enumerate(body.items):
        suffix = f"_{idx}"
        params[f"sku{suffix}"] = item.sku
        params[f"on_hand{suffix}"] = item.on_hand
        params[f"available{suffix}"] = item.available
        params[f"reserved{suffix}"] = item.reserved
        params[f"source_ref{suffix}"] = item.source_ref
        values_clause_parts.append(
            f"(:tenant_id, :facility_id, :sku{suffix}, :on_hand{suffix}, :available{suffix}, :reserved{suffix}, CAST(:as_of AS timestamptz), CAST(:now_iso AS timestamptz), :source_provider, :source_run_id, :source_ref{suffix})"
        )

    values_clause = ", ".join(values_clause_parts)
    sql = text(
        f"""
        INSERT INTO canonical_inventory_items (
            tenant_id, facility_id, sku,
            on_hand, available, reserved,
            as_of, last_seen_at,
            source_provider, source_run_id, source_ref
        )
        VALUES {values_clause}
        ON CONFLICT (tenant_id, facility_id, sku)
        DO UPDATE SET
            on_hand = EXCLUDED.on_hand,
            available = EXCLUDED.available,
            reserved = EXCLUDED.reserved,
            as_of = EXCLUDED.as_of,
            last_seen_at = EXCLUDED.last_seen_at,
            source_provider = EXCLUDED.source_provider,
            source_run_id = EXCLUDED.source_run_id,
            source_ref = EXCLUDED.source_ref
        """
    )
    db.execute(sql, params)
    db.commit()
    return {"ok": True, "upserted": len(body.items)}


def _oos_sql_condition() -> str:
    """Match worker OOS rule: available<=0 when set, else on_hand<=0."""
    return """(
        (available IS NOT NULL AND available <= 0)
        OR (available IS NULL AND on_hand <= 0)
    )"""


@router.get("/items")
def list_inventory_items(
    facility_id: str,
    tenant_id: str | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    oos_only: bool = Query(False, description="Only rows considered out-of-stock (on_hand/available rule)"),
    db: Session = Depends(get_db),
):
    where = ["facility_id = :facility_id"]
    params: dict = {"facility_id": facility_id, "limit": limit, "offset": offset}
    if tenant_id is not None:
        where.append("tenant_id = :tenant_id")
        params["tenant_id"] = tenant_id
    if oos_only:
        where.append(_oos_sql_condition())

    count_sql = text(
        f"SELECT COUNT(*) AS total FROM canonical_inventory_items WHERE {' AND '.join(where)}"
    )
    total = db.execute(count_sql, {k: v for k, v in params.items() if k in ("facility_id", "tenant_id")}).scalar() or 0

    sql = text(
        f"""
        SELECT tenant_id, facility_id, sku, on_hand, available, reserved,
               as_of, last_seen_at, source_provider, source_run_id, source_ref
        FROM canonical_inventory_items
        WHERE {" AND ".join(where)}
        ORDER BY sku ASC
        LIMIT :limit OFFSET :offset
        """
    )
    rows = db.execute(sql, params).mappings().all()
    items = []
    for r in rows:
        row = dict(r)
        for key in ("as_of", "last_seen_at"):
            if row.get(key) is not None and hasattr(row[key], "isoformat"):
                row[key] = row[key].isoformat()
        items.append(row)
    return {"items": items, "limit": limit, "offset": offset, "count": total}


@router.get("/facility-summary")
def get_facility_inventory_summary(
    facility_id: str,
    tenant_id: str,
    db: Session = Depends(get_db),
):
    """Aggregates over canonical inventory for a facility (operator dashboard)."""
    row = db.execute(
        text(
            """
            SELECT EXISTS(
                SELECT 1 FROM facilities WHERE id = :facility_id AND tenant_id = :tenant_id
            ) AS ok
            """
        ),
        {"facility_id": facility_id, "tenant_id": tenant_id},
    ).mappings().first()
    if not row or not row["ok"]:
        raise HTTPException(status_code=404, detail="facility_not_found")

    agg = db.execute(
        text(
            f"""
            SELECT
                COUNT(*)::int AS sku_count,
                COALESCE(SUM(on_hand), 0)::bigint AS total_on_hand,
                COUNT(*) FILTER (WHERE {_oos_sql_condition()})::int AS out_of_stock_count,
                MAX(as_of) AS latest_as_of
            FROM canonical_inventory_items
            WHERE facility_id = :facility_id AND tenant_id = :tenant_id
            """
        ),
        {"facility_id": facility_id, "tenant_id": tenant_id},
    ).mappings().first()
    if agg is None:
        return {
            "facility_id": facility_id,
            "tenant_id": tenant_id,
            "sku_count": 0,
            "total_on_hand": 0,
            "out_of_stock_count": 0,
            "latest_as_of": None,
        }
    out = dict(agg)
    la = out.get("latest_as_of")
    if la is not None and hasattr(la, "isoformat"):
        out["latest_as_of"] = la.isoformat()
    out["facility_id"] = facility_id
    out["tenant_id"] = tenant_id
    return out


@router.get("/facility-history")
def list_facility_inventory_history(
    tenant_id: str,
    facility_id: str,
    limit: int = Query(30, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Recent inventory_snapshot_v0 runs for a facility (parameters.facility_id), newest first."""
    row = db.execute(
        text(
            """
            SELECT EXISTS(
                SELECT 1 FROM facilities WHERE id = :facility_id AND tenant_id = :tenant_id
            ) AS ok
            """
        ),
        {"facility_id": facility_id, "tenant_id": tenant_id},
    ).mappings().first()
    if not row or not row["ok"]:
        raise HTTPException(status_code=404, detail="facility_not_found")

    sql = text(
        """
        WITH recent AS (
            SELECT r.id AS run_id, r.pipeline_version_id, r.status, r.trigger_type,
                   r.created_at, r.finished_at
            FROM pipeline_runs r
            INNER JOIN pipeline_versions pv ON pv.id = r.pipeline_version_id
            WHERE r.tenant_id = :tenant_id
              AND r.parameters->>'facility_id' = :facility_id
              AND pv.dag_spec->>'kind' = 'inventory_snapshot_v0'
            ORDER BY r.created_at DESC
            LIMIT :limit
        )
        SELECT
            recent.run_id,
            recent.pipeline_version_id,
            recent.status,
            recent.trigger_type,
            recent.created_at,
            recent.finished_at,
            art.payload AS artifact_payload
        FROM recent
        LEFT JOIN LATERAL (
            SELECT payload
            FROM pipeline_run_artifacts
            WHERE run_id = recent.run_id AND artifact_type = 'inventory_summary'
            ORDER BY created_at DESC
            LIMIT 1
        ) art ON TRUE
        """
    )
    rows = db.execute(
        sql,
        {"tenant_id": tenant_id, "facility_id": facility_id, "limit": limit},
    ).mappings().all()
    items_out: list[dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        payload = _payload_to_dict(d.pop("artifact_payload", None))
        summary = _artifact_summary_for_history(payload)
        created = d.get("created_at")
        finished = d.get("finished_at")
        items_out.append(
            {
                "run_id": d["run_id"],
                "pipeline_version_id": d["pipeline_version_id"],
                "status": d["status"],
                "trigger_type": d["trigger_type"],
                "created_at": created.isoformat() if created is not None and hasattr(created, "isoformat") else None,
                "finished_at": finished.isoformat() if finished is not None and hasattr(finished, "isoformat") else None,
                **summary,
            }
        )
    return {"items": items_out, "count": len(items_out), "limit": limit}


@router.get("/raw-ingests")
def list_facility_raw_ingests(
    tenant_id: str,
    facility_id: str,
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Recent raw ingest rows for a facility (any run), newest by fetched_at. Operator audit."""
    row = db.execute(
        text(
            """
            SELECT EXISTS(
                SELECT 1 FROM facilities WHERE id = :facility_id AND tenant_id = :tenant_id
            ) AS ok
            """
        ),
        {"facility_id": facility_id, "tenant_id": tenant_id},
    ).mappings().first()
    if not row or not row["ok"]:
        raise HTTPException(status_code=404, detail="facility_not_found")

    rows = db.execute(
        text(
            """
            SELECT id, run_id, tenant_id, facility_id, provider, mapping_version, fetched_at, as_of, payload
            FROM pipeline_run_raw_ingests
            WHERE tenant_id = :tenant_id AND facility_id = :facility_id
            ORDER BY fetched_at DESC
            LIMIT :limit
            """
        ),
        {"tenant_id": tenant_id, "facility_id": facility_id, "limit": limit},
    ).mappings().all()
    items = []
    for r in rows:
        d = dict(r)
        for key in ("fetched_at", "as_of"):
            if d.get(key) is not None and hasattr(d[key], "isoformat"):
                d[key] = d[key].isoformat()
        items.append(d)
    return {"items": items, "count": len(items), "limit": limit}

