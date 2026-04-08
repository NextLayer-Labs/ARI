import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.schemas import ReturnItemsUpsertIn
from app.db.deps import get_db

router = APIRouter(prefix="/api/returns", tags=["returns"])

ATTENTION_PENDING_DAYS = 7


def _payload_to_dict(payload: Any) -> dict | None:
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


def _get_run_tenant(db: Session, run_id: str) -> dict | None:
    row = db.execute(
        text("SELECT id, tenant_id FROM pipeline_runs WHERE id = :run_id"),
        {"run_id": run_id},
    ).mappings().first()
    return dict(row) if row else None


def _needs_attention(status: str, received_at: Any, disposition: Any, created_at_source: Any) -> bool:
    status_l = (status or "").strip().lower()
    if status_l == "received" and not disposition:
        return True
    if status_l == "pending" and created_at_source and hasattr(created_at_source, "tzinfo"):
        now = datetime.now(timezone.utc)
        created_utc = created_at_source.astimezone(timezone.utc)
        age_days = (now - created_utc).days
        return age_days >= ATTENTION_PENDING_DAYS
    return False


def _artifact_summary_for_history(payload: dict | None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "fixture_used": None,
        "returns_count": None,
        "total_units": None,
        "pending_count": None,
        "received_count": None,
        "processed_count": None,
        "needs_attention_count": None,
        "artifact_present": False,
    }
    if not payload:
        return out
    out["artifact_present"] = True
    for key in (
        "fixture_used",
        "returns_count",
        "total_units",
        "pending_count",
        "received_count",
        "processed_count",
        "needs_attention_count",
    ):
        out[key] = payload.get(key)
    return out


@router.post("/items:upsert")
def upsert_return_items(body: ReturnItemsUpsertIn, db: Session = Depends(get_db)):
    if not body.items:
        raise HTTPException(status_code=400, detail="items_required")
    if len(body.items) > 5000:
        raise HTTPException(status_code=400, detail="too_many_items")

    run = _get_run_tenant(db, body.source_run_id)
    if run is None:
        return JSONResponse(status_code=404, content={"ok": False, "reason": "run_not_found"})
    tenant_id = run["tenant_id"]

    for item in body.items:
        if not item.return_id or not isinstance(item.return_id, str):
            raise HTTPException(status_code=400, detail="invalid_return_id")
        if not item.sku or not isinstance(item.sku, str):
            raise HTTPException(status_code=400, detail="invalid_sku")
        if not item.status or not isinstance(item.status, str):
            raise HTTPException(status_code=400, detail="invalid_status")

    now_iso = datetime.now(timezone.utc).isoformat()
    params: dict[str, Any] = {
        "tenant_id": tenant_id,
        "facility_id": body.facility_id,
        "source_provider": body.source_provider,
        "source_run_id": body.source_run_id,
        "now_iso": now_iso,
    }
    values_clause_parts: list[str] = []
    for idx, item in enumerate(body.items):
        s = f"_{idx}"
        params[f"return_id{s}"] = item.return_id
        params[f"order_id{s}"] = item.order_id
        params[f"sku{s}"] = item.sku
        params[f"quantity{s}"] = item.quantity
        params[f"status{s}"] = item.status
        params[f"reason_code{s}"] = item.reason_code
        params[f"created_at_source{s}"] = item.created_at_source
        params[f"updated_at_source{s}"] = item.updated_at_source
        params[f"received_at{s}"] = item.received_at
        params[f"processed_at{s}"] = item.processed_at
        params[f"disposition{s}"] = item.disposition
        values_clause_parts.append(
            f"""(
            :tenant_id, :facility_id, :return_id{s}, :order_id{s}, :sku{s}, :quantity{s}, :status{s}, :reason_code{s},
            CAST(:created_at_source{s} AS timestamptz),
            CAST(:updated_at_source{s} AS timestamptz),
            CAST(:received_at{s} AS timestamptz),
            CAST(:processed_at{s} AS timestamptz),
            :disposition{s}, :source_provider, :source_run_id, CAST(:now_iso AS timestamptz)
            )"""
        )

    sql = text(
        f"""
        INSERT INTO canonical_return_items (
            tenant_id, facility_id, return_id, order_id, sku, quantity, status, reason_code,
            created_at_source, updated_at_source, received_at, processed_at, disposition,
            source_provider, source_run_id, last_seen_at
        )
        VALUES {", ".join(values_clause_parts)}
        ON CONFLICT (tenant_id, facility_id, return_id)
        DO UPDATE SET
            order_id = EXCLUDED.order_id,
            sku = EXCLUDED.sku,
            quantity = EXCLUDED.quantity,
            status = EXCLUDED.status,
            reason_code = EXCLUDED.reason_code,
            created_at_source = EXCLUDED.created_at_source,
            updated_at_source = EXCLUDED.updated_at_source,
            received_at = EXCLUDED.received_at,
            processed_at = EXCLUDED.processed_at,
            disposition = EXCLUDED.disposition,
            source_provider = EXCLUDED.source_provider,
            source_run_id = EXCLUDED.source_run_id,
            last_seen_at = EXCLUDED.last_seen_at
        """
    )
    db.execute(sql, params)
    db.commit()
    return {"ok": True, "upserted": len(body.items)}


@router.get("/items")
def list_return_items(
    facility_id: str,
    tenant_id: str | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    where = ["facility_id = :facility_id"]
    params: dict[str, Any] = {"facility_id": facility_id, "limit": limit, "offset": offset}
    if tenant_id is not None:
        where.append("tenant_id = :tenant_id")
        params["tenant_id"] = tenant_id

    total = db.execute(
        text(f"SELECT COUNT(*) AS total FROM canonical_return_items WHERE {' AND '.join(where)}"),
        {k: v for k, v in params.items() if k in ("facility_id", "tenant_id")},
    ).scalar() or 0
    rows = db.execute(
        text(
            f"""
            SELECT tenant_id, facility_id, return_id, order_id, sku, quantity, status, reason_code,
                   created_at_source, updated_at_source, received_at, processed_at, disposition,
                   source_provider, source_run_id, last_seen_at
            FROM canonical_return_items
            WHERE {' AND '.join(where)}
            ORDER BY return_id ASC
            LIMIT :limit OFFSET :offset
            """
        ),
        params,
    ).mappings().all()
    items = []
    for r in rows:
        d = dict(r)
        for key in (
            "created_at_source",
            "updated_at_source",
            "received_at",
            "processed_at",
            "last_seen_at",
        ):
            if d.get(key) is not None and hasattr(d[key], "isoformat"):
                d[key] = d[key].isoformat()
        items.append(d)
    return {"items": items, "limit": limit, "offset": offset, "count": total}


@router.get("/facility-summary")
def get_facility_returns_summary(facility_id: str, tenant_id: str, db: Session = Depends(get_db)):
    row = db.execute(
        text("SELECT EXISTS(SELECT 1 FROM facilities WHERE id = :facility_id AND tenant_id = :tenant_id) AS ok"),
        {"facility_id": facility_id, "tenant_id": tenant_id},
    ).mappings().first()
    if not row or not row["ok"]:
        raise HTTPException(status_code=404, detail="facility_not_found")

    rows = db.execute(
        text(
            """
            SELECT status, quantity, received_at, disposition, created_at_source
            FROM canonical_return_items
            WHERE tenant_id = :tenant_id AND facility_id = :facility_id
            """
        ),
        {"tenant_id": tenant_id, "facility_id": facility_id},
    ).mappings().all()
    returns_count = len(rows)
    total_units = sum(int(r.get("quantity") or 0) for r in rows)
    pending_count = sum(1 for r in rows if str(r.get("status") or "").lower() == "pending")
    received_count = sum(1 for r in rows if str(r.get("status") or "").lower() == "received")
    processed_count = sum(1 for r in rows if str(r.get("status") or "").lower() == "processed")
    needs_attention_count = sum(
        1
        for r in rows
        if _needs_attention(
            str(r.get("status") or ""),
            r.get("received_at"),
            r.get("disposition"),
            r.get("created_at_source"),
        )
    )
    open_ages = []
    now = datetime.now(timezone.utc)
    for r in rows:
        status_l = str(r.get("status") or "").lower()
        created = r.get("created_at_source")
        if status_l in ("pending", "received") and created and hasattr(created, "tzinfo"):
            open_ages.append((now - created.astimezone(timezone.utc)).days)
    oldest_open_age_days = max(open_ages) if open_ages else None

    return {
        "facility_id": facility_id,
        "tenant_id": tenant_id,
        "returns_count": returns_count,
        "total_units": total_units,
        "pending_count": pending_count,
        "received_count": received_count,
        "processed_count": processed_count,
        "needs_attention_count": needs_attention_count,
        "oldest_open_age_days": oldest_open_age_days,
    }


@router.get("/facility-history")
def list_facility_returns_history(
    tenant_id: str,
    facility_id: str,
    limit: int = Query(30, ge=1, le=100),
    db: Session = Depends(get_db),
):
    row = db.execute(
        text("SELECT EXISTS(SELECT 1 FROM facilities WHERE id = :facility_id AND tenant_id = :tenant_id) AS ok"),
        {"facility_id": facility_id, "tenant_id": tenant_id},
    ).mappings().first()
    if not row or not row["ok"]:
        raise HTTPException(status_code=404, detail="facility_not_found")

    rows = db.execute(
        text(
            """
            WITH recent AS (
                SELECT r.id AS run_id, r.pipeline_version_id, r.status, r.trigger_type, r.created_at, r.finished_at
                FROM pipeline_runs r
                INNER JOIN pipeline_versions pv ON pv.id = r.pipeline_version_id
                WHERE r.tenant_id = :tenant_id
                  AND r.parameters->>'facility_id' = :facility_id
                  AND pv.dag_spec->>'kind' = 'returns_snapshot_v0'
                ORDER BY r.created_at DESC
                LIMIT :limit
            )
            SELECT recent.run_id, recent.pipeline_version_id, recent.status, recent.trigger_type,
                   recent.created_at, recent.finished_at, art.payload AS artifact_payload
            FROM recent
            LEFT JOIN LATERAL (
                SELECT payload
                FROM pipeline_run_artifacts
                WHERE run_id = recent.run_id AND artifact_type = 'returns_summary'
                ORDER BY created_at DESC
                LIMIT 1
            ) art ON TRUE
            """
        ),
        {"tenant_id": tenant_id, "facility_id": facility_id, "limit": limit},
    ).mappings().all()
    out_items: list[dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        payload = _payload_to_dict(d.pop("artifact_payload", None))
        summary = _artifact_summary_for_history(payload)
        created = d.get("created_at")
        finished = d.get("finished_at")
        out_items.append(
            {
                "run_id": d["run_id"],
                "pipeline_version_id": d["pipeline_version_id"],
                "status": d["status"],
                "trigger_type": d["trigger_type"],
                "created_at": created.isoformat() if created is not None and hasattr(created, "isoformat") else None,
                "finished_at": finished.isoformat()
                if finished is not None and hasattr(finished, "isoformat")
                else None,
                **summary,
            }
        )
    return {"items": out_items, "count": len(out_items), "limit": limit}


@router.get("/approved-snapshot-versions")
def list_approved_returns_snapshot_versions(tenant_id: str, db: Session = Depends(get_db)):
    ok = db.execute(text("SELECT 1 FROM tenants WHERE id = :id LIMIT 1"), {"id": tenant_id}).scalar()
    if not ok:
        raise HTTPException(status_code=404, detail="tenant_not_found")

    rows = db.execute(
        text(
            """
            SELECT pv.id, pv.pipeline_id, pv.version, pv.created_at, p.name AS pipeline_name
            FROM pipeline_versions pv
            LEFT JOIN pipelines p ON p.id = pv.pipeline_id
            WHERE pv.tenant_id = :tenant_id
              AND pv.status = 'APPROVED'
              AND (pv.dag_spec->>'kind') = 'returns_snapshot_v0'
            ORDER BY pv.created_at DESC
            LIMIT 50
            """
        ),
        {"tenant_id": tenant_id},
    ).mappings().all()
    items = []
    for r in rows:
        d = dict(r)
        ca = d.get("created_at")
        if ca is not None and hasattr(ca, "isoformat"):
            d["created_at"] = ca.isoformat()
        items.append(d)
    return {"items": items, "count": len(items)}
