import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.schemas import (
    LogAppendIn,
    RawIngestCreateIn,
    RunArtifactCreateIn,
    RunClaimIn,
    RunCompleteIn,
    RetryIn,
    HeartbeatIn,
    ReapStaleIn,
)
from app.api.inventory_logic import InventorySnapshotError, build_run_inventory_snapshot
from app.db.deps import get_db
from app.models.core import PipelineRun, PipelineVersion

router = APIRouter(prefix="/api/runs", tags=["runs"])


def _pipeline_run_columns(db: Session) -> set[str]:
    rows = db.execute(
        text(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'pipeline_runs'
            """
        )
    ).fetchall()
    return {row[0] for row in rows}


def _run_returning_sql(columns: set[str]) -> str:
    claimed_at = "claimed_at" if "claimed_at" in columns else "NULL::timestamptz AS claimed_at"
    claimed_by = "claimed_by" if "claimed_by" in columns else "NULL::text AS claimed_by"
    error_message = "error_message" if "error_message" in columns else "NULL::text AS error_message"
    return f"""
        id,
        tenant_id,
        pipeline_version_id,
        trigger_type,
        parameters,
        status,
        started_at,
        {claimed_at},
        {claimed_by},
        finished_at,
        {error_message}
    """


@router.post("/claim")
def claim_run(body: RunClaimIn, db: Session = Depends(get_db)):
    tenant_filter = ""
    params: dict[str, str] = {"worker_id": body.worker_id}
    if body.tenant_id:
        tenant_filter = "AND r.tenant_id = :tenant_id"
        params["tenant_id"] = body.tenant_id

    with db.begin():
        run_columns = _pipeline_run_columns(db)

        row = db.execute(
            text(
                f"""
                SELECT r.id
                FROM pipeline_runs r
                WHERE r.status = 'QUEUED'
                {tenant_filter}
                ORDER BY r.created_at ASC
                FOR UPDATE SKIP LOCKED
                LIMIT 1
                """
            ),
            params,
        ).mappings().first()

        if row is None:
            return {"claimed": False}

        set_clauses = [
            "status='RUNNING'",
            "started_at=COALESCE(started_at, NOW())",
        ]
        if "claimed_at" in run_columns:
            set_clauses.append("claimed_at=NOW()")
        if "claimed_by" in run_columns:
            set_clauses.append("claimed_by=:worker_id")
        if "heartbeat_at" in run_columns:
            set_clauses.append("heartbeat_at=NOW()")
        if "updated_at" in run_columns:
            set_clauses.append("updated_at=NOW()")

        run = db.execute(
            text(
                f"""
                UPDATE pipeline_runs
                SET {", ".join(set_clauses)}
                WHERE id=:run_id
                RETURNING {_run_returning_sql(run_columns)}
                """
            ),
            {"run_id": row["id"], "worker_id": body.worker_id},
        ).mappings().one()

        pipeline_version = db.execute(
            text(
                """
                SELECT id, status, dag_spec
                FROM pipeline_versions
                WHERE id=:pipeline_version_id
                """
            ),
            {"pipeline_version_id": run["pipeline_version_id"]},
        ).mappings().first()

        if pipeline_version is None:
            raise HTTPException(status_code=409, detail="pipeline version not found for claimed run")

    return {
        "claimed": True,
        "run": dict(run),
        "pipeline_version": dict(pipeline_version),
    }


@router.post("/{run_id}/complete")
def complete_run(run_id: str, body: RunCompleteIn, db: Session = Depends(get_db)):
    with db.begin():
        run_columns = _pipeline_run_columns(db)
        set_clauses = [
            "status=CAST(:status AS VARCHAR)",
            "finished_at=NOW()",
        ]
        if "heartbeat_at" in run_columns:
            set_clauses.append("heartbeat_at=NOW()")
        if "error_message" in run_columns:
            set_clauses.append(
                "error_message=CASE WHEN CAST(:status AS VARCHAR)='FAILED' THEN :error_message ELSE NULL END"
            )
        if "updated_at" in run_columns:
            set_clauses.append("updated_at=NOW()")

        run = db.execute(
            text(
                f"""
                UPDATE pipeline_runs
                SET {", ".join(set_clauses)}
                WHERE id=:run_id AND status='RUNNING'
                RETURNING {_run_returning_sql(run_columns)}
                """
            ),
            {
                "run_id": run_id,
                "status": body.status,
                "error_message": body.error_message,
            },
        ).mappings().first()

        if run is None:
            raise HTTPException(
                status_code=409,
                detail="run not RUNNING or not found",
            )

    return {"ok": True, "run": dict(run)}


@router.get("")
def list_runs(
    tenant_id: str | None = None,
    status: str | None = None,
    retry_of_run_id: str | None = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    where = ["1=1"]
    params: dict = {"limit": limit, "offset": offset}

    if tenant_id is not None:
        where.append("tenant_id = :tenant_id")
        params["tenant_id"] = str(tenant_id)

    if status is not None:
        where.append("status = CAST(:status AS VARCHAR)")
        params["status"] = status

    if retry_of_run_id is not None:
        where.append("retry_of_run_id = :retry_of_run_id")
        params["retry_of_run_id"] = str(retry_of_run_id)

    sql = text(f"""
SELECT id, tenant_id, pipeline_version_id, status, trigger_type, parameters,
       claimed_by, claimed_at, started_at, finished_at, heartbeat_at, error_message,
       created_at, updated_at,
       retry_of_run_id, root_run_id
FROM pipeline_runs
WHERE {" AND ".join(where)}
ORDER BY created_at DESC
LIMIT :limit OFFSET :offset
""")
    rows = db.execute(sql, params).mappings().all()
    return {"items": [_serialize_run(dict(r)) for r in rows], "limit": limit, "offset": offset, "count": len(rows)}


@router.post("/reap-stale")
def reap_stale(body: ReapStaleIn, db: Session = Depends(get_db)):
    """Mark RUNNING runs with no recent heartbeat as FAILED. Manual trigger."""
    limit = max(1, min(body.limit, 500))
    stale_seconds = max(1, body.stale_after_seconds)
    with db.begin():
        rows = db.execute(
            text(
                """
                SELECT id, tenant_id, heartbeat_at
                FROM pipeline_runs
                WHERE status = 'RUNNING'
                  AND (heartbeat_at IS NULL OR heartbeat_at < NOW() - CAST(:stale_seconds AS integer) * INTERVAL '1 second')
                ORDER BY created_at ASC
                LIMIT :limit
                FOR UPDATE SKIP LOCKED
                """
            ),
            {"stale_seconds": stale_seconds, "limit": limit},
        ).mappings().all()
        run_ids = []
        for row in rows:
            run_id = row["id"]
            run_ids.append(run_id)
            last_hb = row["heartbeat_at"]
            last_hb_iso = last_hb.isoformat() if last_hb is not None else None
            meta = {"stale_after_seconds": stale_seconds}
            if last_hb_iso is not None:
                meta["last_heartbeat_at"] = last_hb_iso
            meta_json = json.dumps(meta)
            db.execute(
                text(
                    """
                    UPDATE pipeline_runs
                    SET status = 'FAILED', finished_at = NOW(), updated_at = NOW(),
                        error_message = :error_message
                    WHERE id = :run_id
                    """
                ),
                {"run_id": run_id, "error_message": f"Stale: no heartbeat for {stale_seconds}s"},
            )
            db.execute(
                text(
                    """
                    INSERT INTO pipeline_run_logs (id, run_id, tenant_id, level, message, source, meta)
                    VALUES (gen_random_uuid()::text, :run_id, :tenant_id, :level, :message, :source, CAST(:meta AS jsonb))
                    """
                ),
                {
                    "run_id": run_id,
                    "tenant_id": row["tenant_id"],
                    "level": "WARN",
                    "message": "Run marked stale by reaper",
                    "source": "control-plane",
                    "meta": meta_json,
                },
            )
    return {"ok": True, "reaped": len(run_ids), "run_ids": run_ids}


@router.get("/{run_id}")
def get_run(run_id: str, db: Session = Depends(get_db)):
    row = db.execute(
        text(
            """
            SELECT id, tenant_id, pipeline_version_id, status, trigger_type, parameters,
                   claimed_by, claimed_at, started_at, finished_at, heartbeat_at, error_message,
                   created_at, updated_at,
                   retry_of_run_id, root_run_id
            FROM pipeline_runs
            WHERE id = :run_id
            """
        ),
        {"run_id": run_id},
    ).mappings().first()
    if row is None:
        return JSONResponse(
            status_code=404,
            content={"found": False, "reason": "run_not_found"},
        )
    return {"found": True, "run": _serialize_run(dict(row))}


@router.post("/{run_id}/heartbeat")
def heartbeat_run(run_id: str, body: HeartbeatIn, db: Session = Depends(get_db)):
    """Update heartbeat_at for a RUNNING run; only the claiming worker may heartbeat."""
    run = _get_run_full(db, run_id)
    if run is None:
        return JSONResponse(
            status_code=404,
            content={"ok": False, "reason": "run_not_found"},
        )
    if run.get("status") != "RUNNING":
        return JSONResponse(
            status_code=409,
            content={"ok": False, "reason": "not_running", "status": run.get("status")},
        )
    claimed_by = run.get("claimed_by")
    if claimed_by != body.worker_id:
        return JSONResponse(
            status_code=409,
            content={"ok": False, "reason": "worker_mismatch", "claimed_by": claimed_by},
        )
    run_columns = _pipeline_run_columns(db)
    set_clauses = ["heartbeat_at = NOW()"]
    if "updated_at" in run_columns:
        set_clauses.append("updated_at = NOW()")
    db.execute(
        text(
            f"""
            UPDATE pipeline_runs
            SET {", ".join(set_clauses)}
            WHERE id = :run_id AND status = 'RUNNING' AND claimed_by = :worker_id
            """
        ),
        {"run_id": run_id, "worker_id": body.worker_id},
    )
    db.commit()
    now_utc = datetime.now(timezone.utc)
    return {"ok": True, "heartbeat_at": now_utc.isoformat()}


def _run_exists(db: Session, run_id: str) -> dict | None:
    row = db.execute(
        text("SELECT id, tenant_id FROM pipeline_runs WHERE id = :run_id"),
        {"run_id": run_id},
    ).mappings().first()
    return dict(row) if row else None


def _get_run_full(db: Session, run_id: str) -> dict | None:
    row = db.execute(
        text(
            """
            SELECT id, tenant_id, pipeline_version_id, status, trigger_type, parameters,
                   claimed_by, claimed_at, started_at, finished_at, heartbeat_at, error_message,
                   created_at, updated_at,
                   retry_of_run_id, root_run_id
            FROM pipeline_runs
            WHERE id = :run_id
            """
        ),
        {"run_id": run_id},
    ).mappings().first()
    return dict(row) if row else None


def _serialize_run(r: dict) -> dict:
    """Convert run row dict to JSON-safe dict with ISO timestamps."""
    out = dict(r)
    for key in ("created_at", "updated_at", "started_at", "claimed_at", "finished_at", "heartbeat_at"):
        if out.get(key) is not None and hasattr(out[key], "isoformat"):
            out[key] = out[key].isoformat()
    return out


def _serialize_artifact(a: dict) -> dict:
    out = dict(a)
    if out.get("created_at") is not None and hasattr(out["created_at"], "isoformat"):
        out["created_at"] = out["created_at"].isoformat()
    return out


@router.post("/{run_id}/cancel")
def cancel_run(run_id: str, db: Session = Depends(get_db)):
    run = _get_run_full(db, run_id)
    if run is None:
        return JSONResponse(
            status_code=404,
            content={"ok": False, "reason": "run_not_found"},
        )
    status = run.get("status")
    if status not in ("QUEUED", "RUNNING"):
        return JSONResponse(
            status_code=409,
            content={"ok": False, "reason": "invalid_state", "status": status},
        )
    run_columns = _pipeline_run_columns(db)
    set_clauses = [
        "status = 'CANCELLED'",
        "finished_at = NOW()",
    ]
    if "updated_at" in run_columns:
        set_clauses.append("updated_at = NOW()")
    if "error_message" in run_columns:
        set_clauses.append("error_message = 'Cancelled by admin'")
    db.execute(
        text(
            f"""
            UPDATE pipeline_runs
            SET {", ".join(set_clauses)}
            WHERE id = :run_id AND status IN ('QUEUED', 'RUNNING')
            """
        ),
        {"run_id": run_id},
    )
    meta_json = json.dumps({"status": "CANCELLED"})
    db.execute(
        text(
            """
            INSERT INTO pipeline_run_logs (id, run_id, tenant_id, level, message, source, meta)
            VALUES (gen_random_uuid()::text, :run_id, :tenant_id, :level, :message, :source, CAST(:meta AS jsonb))
            """
        ),
        {
            "run_id": run_id,
            "tenant_id": run["tenant_id"],
            "level": "WARN",
            "message": "Run cancelled",
            "source": "control-plane",
            "meta": meta_json,
        },
    )
    db.commit()
    updated = _get_run_full(db, run_id)
    return {"ok": True, "run": _serialize_run(updated)} if updated else {"ok": False, "reason": "run_not_found"}


@router.post("/{run_id}/retry")
def retry_run(run_id: str, body: RetryIn | None = None, db: Session = Depends(get_db)):
    run = _get_run_full(db, run_id)
    if run is None:
        return JSONResponse(
            status_code=404,
            content={"ok": False, "reason": "run_not_found"},
        )
    status = run.get("status")
    if status not in ("FAILED", "CANCELLED"):
        return JSONResponse(
            status_code=409,
            content={"ok": False, "reason": "invalid_state", "status": status},
        )
    pv = db.get(PipelineVersion, run["pipeline_version_id"])
    if not pv:
        return JSONResponse(status_code=409, content={"ok": False, "reason": "pipeline_version_not_found"})
    if pv.status != "APPROVED":
        return JSONResponse(status_code=400, content={"ok": False, "reason": "pipeline_version_not_approved"})
    parameters = run["parameters"] if run.get("parameters") is not None else {}
    if body is not None and body.parameters is not None:
        parameters = body.parameters
    root_run_id = run.get("root_run_id") if run.get("root_run_id") else run_id
    new_run = PipelineRun(
        tenant_id=run["tenant_id"],
        pipeline_version_id=run["pipeline_version_id"],
        trigger_type="retry",
        parameters=parameters,
        status="QUEUED",
        retry_of_run_id=run_id,
        root_run_id=root_run_id,
    )
    db.add(new_run)
    db.commit()
    db.refresh(new_run)
    new_run_id = new_run.id
    meta_retry = json.dumps({"retry_of": run_id})
    db.execute(
        text(
            """
            INSERT INTO pipeline_run_logs (id, run_id, tenant_id, level, message, source, meta)
            VALUES (gen_random_uuid()::text, :run_id, :tenant_id, :level, :message, :source, CAST(:meta AS jsonb))
            """
        ),
        {
            "run_id": new_run_id,
            "tenant_id": new_run.tenant_id,
            "level": "INFO",
            "message": f"Retry of {run_id}",
            "source": "control-plane",
            "meta": meta_retry,
        },
    )
    db.commit()
    new_run_row = _get_run_full(db, new_run_id)
    return {
        "ok": True,
        "run": _serialize_run(new_run_row) if new_run_row else {"id": new_run_id},
        "retry_of": run_id,
    }


@router.post("/{run_id}/logs")
def append_run_log(run_id: str, body: LogAppendIn, db: Session = Depends(get_db)):
    run = _run_exists(db, run_id)
    if run is None:
        return JSONResponse(
            status_code=404,
            content={"found": False, "reason": "run_not_found"},
        )
    meta_json = json.dumps(body.meta) if body.meta is not None else None
    row = db.execute(
        text(
            """
            INSERT INTO pipeline_run_logs (id, run_id, tenant_id, level, message, source, meta)
            VALUES (gen_random_uuid()::text, :run_id, :tenant_id, :level, :message, :source, CAST(:meta AS jsonb))
            RETURNING id, ts, level, message, source, meta
            """
        ),
        {
            "run_id": run_id,
            "tenant_id": run["tenant_id"],
            "level": body.level,
            "message": body.message,
            "source": body.source,
            "meta": meta_json,
        },
    ).mappings().one()
    db.commit()
    out = dict(row)
    if out.get("ts"):
        out["ts"] = out["ts"].isoformat()
    return {"ok": True, "log": out}


@router.get("/{run_id}/logs")
def get_run_logs(
    run_id: str,
    limit: int = Query(200, ge=1, le=1000),
    before_ts: str | None = Query(None, description="ISO timestamp for pagination backwards"),
    after_ts: str | None = Query(None, description="ISO timestamp for tailing"),
    order: str = Query("asc", description="asc or desc"),
    db: Session = Depends(get_db),
):
    run = _run_exists(db, run_id)
    if run is None:
        return JSONResponse(
            status_code=404,
            content={"found": False, "run_id": run_id, "logs": []},
        )
    order_dir = "DESC" if order.lower() == "desc" else "ASC"
    params: dict = {"run_id": run_id, "limit": limit}
    conditions = ["run_id = :run_id"]
    if before_ts:
        conditions.append("ts < CAST(:before_ts AS timestamptz)")
        params["before_ts"] = before_ts
    if after_ts:
        conditions.append("ts > CAST(:after_ts AS timestamptz)")
        params["after_ts"] = after_ts
    sql = text(
        f"""
        SELECT id, ts, level, message, source, meta
        FROM pipeline_run_logs
        WHERE {" AND ".join(conditions)}
        ORDER BY ts {order_dir}
        LIMIT :limit
        """
    )
    rows = db.execute(sql, params).mappings().all()
    logs = []
    for r in rows:
        row_dict = dict(r)
        if row_dict.get("ts"):
            row_dict["ts"] = row_dict["ts"].isoformat()
        logs.append(row_dict)
    return {"found": True, "run_id": run_id, "logs": logs}


@router.post("/{run_id}/raw-ingests")
def create_run_raw_ingest(run_id: str, body: RawIngestCreateIn, db: Session = Depends(get_db)):
    """Create a raw ingest row for a run, storing the provider payload as jsonb."""
    run = _run_exists(db, run_id)
    if run is None:
        return JSONResponse(
            status_code=404,
            content={"ok": False, "reason": "run_not_found"},
        )
    if not isinstance(body.payload, dict):
        raise HTTPException(status_code=400, detail="payload_must_be_object")
    payload_json = json.dumps(body.payload)
    row = db.execute(
        text(
            """
            INSERT INTO pipeline_run_raw_ingests (
                id, run_id, tenant_id, facility_id, provider, mapping_version, fetched_at, as_of, payload
            )
            VALUES (
                gen_random_uuid()::text,
                :run_id,
                :tenant_id,
                :facility_id,
                :provider,
                :mapping_version,
                NOW(),
                CAST(:as_of AS timestamptz),
                CAST(:payload AS jsonb)
            )
            RETURNING id, run_id, tenant_id, facility_id, provider, mapping_version, fetched_at, as_of, payload
            """
        ),
        {
            "run_id": run_id,
            "tenant_id": run["tenant_id"],
            "facility_id": body.facility_id,
            "provider": body.provider,
            "mapping_version": body.mapping_version,
            "as_of": body.as_of,
            "payload": payload_json,
        },
    ).mappings().one()
    db.commit()
    out = dict(row)
    for key in ("fetched_at", "as_of"):
        if out.get(key) is not None and hasattr(out[key], "isoformat"):
            out[key] = out[key].isoformat()
    return {"ok": True, "raw_ingest": out}


@router.get("/{run_id}/raw-ingests")
def list_run_raw_ingests(
    run_id: str,
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """List raw ingest rows for a run (newest first). Operator audit / replay."""
    run = _run_exists(db, run_id)
    if run is None:
        return JSONResponse(
            status_code=404,
            content={"ok": False, "reason": "run_not_found"},
        )
    rows = db.execute(
        text(
            """
            SELECT id, run_id, tenant_id, facility_id, provider, mapping_version, fetched_at, as_of, payload
            FROM pipeline_run_raw_ingests
            WHERE run_id = :run_id
            ORDER BY fetched_at DESC
            LIMIT :limit
            """
        ),
        {"run_id": run_id, "limit": limit},
    ).mappings().all()
    items = []
    for r in rows:
        d = dict(r)
        for key in ("fetched_at", "as_of"):
            if d.get(key) is not None and hasattr(d[key], "isoformat"):
                d[key] = d[key].isoformat()
        items.append(d)
    return {"found": True, "run_id": run_id, "items": items, "limit": limit}


@router.get("/{run_id}/inventory-snapshot")
def get_run_inventory_snapshot(run_id: str, db: Session = Depends(get_db)):
    """
    Normalized inventory rows from this run's latest raw ingest fixture (inventory_snapshot_v0).
    Not the live canonical table; use for audit and run-to-run comparison.
    """
    try:
        data = build_run_inventory_snapshot(db, run_id)
    except InventorySnapshotError as e:
        return JSONResponse(
            status_code=e.status_code,
            content={"ok": False, "reason": e.reason, "message": e.message},
        )
    return {"ok": True, **data}


@router.post("/{run_id}/artifacts")
def create_run_artifact(run_id: str, body: RunArtifactCreateIn, db: Session = Depends(get_db)):
    run = _run_exists(db, run_id)
    if run is None:
        return JSONResponse(
            status_code=404,
            content={"ok": False, "reason": "run_not_found"},
        )
    if not isinstance(body.payload, dict):
        raise HTTPException(status_code=400, detail="payload_must_be_object")
    payload_json = json.dumps(body.payload)
    meta_json = json.dumps(body.meta) if body.meta is not None else None
    row = db.execute(
        text(
            """
            INSERT INTO pipeline_run_artifacts (id, run_id, tenant_id, created_at, artifact_type, payload, source, meta)
            VALUES (
                gen_random_uuid()::text,
                :run_id,
                :tenant_id,
                NOW(),
                :artifact_type,
                CAST(:payload AS jsonb),
                :source,
                CAST(:meta AS jsonb)
            )
            RETURNING id, run_id, tenant_id, created_at, artifact_type, payload, source, meta
            """
        ),
        {
            "run_id": run_id,
            "tenant_id": run["tenant_id"],
            "artifact_type": body.artifact_type,
            "payload": payload_json,
            "source": body.source,
            "meta": meta_json,
        },
    ).mappings().one()
    db.commit()
    return {"ok": True, "artifact": _serialize_artifact(dict(row))}


@router.get("/{run_id}/artifacts")
def get_run_artifacts(
    run_id: str,
    artifact_type: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    order: str = Query("asc"),
    db: Session = Depends(get_db),
):
    run = _run_exists(db, run_id)
    if run is None:
        return JSONResponse(
            status_code=404,
            content={"found": False, "reason": "run_not_found"},
        )
    order_dir = "DESC" if order.lower() == "desc" else "ASC"
    params: dict = {"run_id": run_id, "limit": limit}
    conditions = ["run_id = :run_id"]
    if artifact_type is not None:
        conditions.append("artifact_type = :artifact_type")
        params["artifact_type"] = artifact_type
    sql = text(
        f"""
        SELECT id, run_id, tenant_id, created_at, artifact_type, payload, source, meta
        FROM pipeline_run_artifacts
        WHERE {" AND ".join(conditions)}
        ORDER BY created_at {order_dir}
        LIMIT :limit
        """
    )
    rows = db.execute(sql, params).mappings().all()
    items = [_serialize_artifact(dict(r)) for r in rows]
    return {"items": items, "count": len(items), "limit": limit}
