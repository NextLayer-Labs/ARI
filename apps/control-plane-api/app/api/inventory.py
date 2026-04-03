import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.schemas import InventoryItemsUpsertIn
from app.db.deps import get_db


router = APIRouter(prefix="/api/inventory", tags=["inventory"])


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


@router.get("/items")
def list_inventory_items(
    facility_id: str,
    tenant_id: str | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    where = ["facility_id = :facility_id"]
    params: dict = {"facility_id": facility_id, "limit": limit, "offset": offset}
    if tenant_id is not None:
        where.append("tenant_id = :tenant_id")
        params["tenant_id"] = tenant_id

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

