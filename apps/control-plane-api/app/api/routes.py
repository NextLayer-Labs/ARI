from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.deps import get_db
from app.models.core import Tenant, Facility, ConnectorInstance, Pipeline, PipelineVersion, PipelineRun
from app.api.schemas import (
    TenantCreate, TenantOut,
    FacilityCreate, FacilityOut,
    ConnectorInstanceCreate, ConnectorInstanceOut,
    PipelineCreate, PipelineOut,
    PipelineVersionCreate, PipelineVersionOut, ApproveVersionIn,
    RunCreate, RunOut,
)

router = APIRouter()

@router.post("/tenants", response_model=TenantOut)
def create_tenant(body: TenantCreate, db: Session = Depends(get_db)):
    t = Tenant(name=body.name)
    db.add(t)
    db.commit()
    db.refresh(t)
    return TenantOut(id=t.id, name=t.name)

@router.post("/facilities", response_model=FacilityOut)
def create_facility(body: FacilityCreate, db: Session = Depends(get_db)):
    tenant = db.get(Tenant, body.tenant_id)
    if not tenant:
        raise HTTPException(404, "tenant not found")
    f = Facility(
        tenant_id=body.tenant_id,
        name=body.name,
        facility_type=body.facility_type,
        timezone=body.timezone,
    )
    db.add(f)
    db.commit()
    db.refresh(f)
    return FacilityOut(id=f.id, tenant_id=f.tenant_id, name=f.name, facility_type=f.facility_type, timezone=f.timezone)

@router.post("/connector-instances", response_model=ConnectorInstanceOut)
def create_connector_instance(body: ConnectorInstanceCreate, db: Session = Depends(get_db)):
    if not db.get(Tenant, body.tenant_id):
        raise HTTPException(404, "tenant not found")
    if body.facility_id and not db.get(Facility, body.facility_id):
        raise HTTPException(404, "facility not found")

    ci = ConnectorInstance(
        tenant_id=body.tenant_id,
        facility_id=body.facility_id,
        connector_type=body.connector_type,
        config=body.config,
        secrets_ref=body.secrets_ref,
    )
    db.add(ci)
    db.commit()
    db.refresh(ci)
    return ConnectorInstanceOut(
        id=ci.id, tenant_id=ci.tenant_id, facility_id=ci.facility_id,
        connector_type=ci.connector_type, status=ci.status,
        config=ci.config, secrets_ref=ci.secrets_ref
    )

@router.post("/pipelines", response_model=PipelineOut)
def create_pipeline(body: PipelineCreate, db: Session = Depends(get_db)):
    if not db.get(Tenant, body.tenant_id):
        raise HTTPException(404, "tenant not found")
    p = Pipeline(tenant_id=body.tenant_id, name=body.name, description=body.description)
    db.add(p)
    db.commit()
    db.refresh(p)
    return PipelineOut(id=p.id, tenant_id=p.tenant_id, name=p.name, description=p.description)

@router.post("/pipeline-versions", response_model=PipelineVersionOut)
def create_pipeline_version(body: PipelineVersionCreate, db: Session = Depends(get_db)):
    if not db.get(Tenant, body.tenant_id):
        raise HTTPException(404, "tenant not found")
    if not db.get(Pipeline, body.pipeline_id):
        raise HTTPException(404, "pipeline not found")

    pv = PipelineVersion(
        tenant_id=body.tenant_id,
        pipeline_id=body.pipeline_id,
        version=body.version,
        status="DRAFT",
        dag_spec=body.dag_spec,
    )
    db.add(pv)
    db.commit()
    db.refresh(pv)
    return PipelineVersionOut(
        id=pv.id, tenant_id=pv.tenant_id, pipeline_id=pv.pipeline_id,
        version=pv.version, status=pv.status, dag_spec=pv.dag_spec
    )

@router.get("/pipelines")
def list_pipelines(
    tenant_id: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    where = ["1=1"]
    params: dict = {"limit": limit, "offset": offset}
    if tenant_id is not None:
        where.append("tenant_id = :tenant_id")
        params["tenant_id"] = str(tenant_id)

    count_params = {k: v for k, v in params.items() if k in ("tenant_id",)}
    count_sql = text(
        f"SELECT COUNT(*) AS total FROM pipelines WHERE {' AND '.join(where)}"
    )
    total = db.execute(count_sql, count_params).scalar() or 0

    sql = text(
        f"""
        SELECT id, tenant_id, name, description, created_at
        FROM pipelines
        WHERE {' AND '.join(where)}
        ORDER BY created_at DESC
        LIMIT :limit OFFSET :offset
        """
    )
    rows = db.execute(sql, params).mappings().all()
    items = []
    for r in rows:
        row_dict = dict(r)
        if row_dict.get("created_at"):
            row_dict["created_at"] = row_dict["created_at"].isoformat()
        items.append(row_dict)
    return {"items": items, "limit": limit, "offset": offset, "total": total}


@router.get("/pipeline-versions")
def list_pipeline_versions(
    tenant_id: str | None = None,
    pipeline_id: str | None = None,
    status: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    where = ["1=1"]
    params: dict = {"limit": limit, "offset": offset}
    if tenant_id is not None:
        where.append("pv.tenant_id = :tenant_id")
        params["tenant_id"] = str(tenant_id)
    if pipeline_id is not None:
        where.append("pv.pipeline_id = :pipeline_id")
        params["pipeline_id"] = str(pipeline_id)
    if status is not None:
        where.append("pv.status = CAST(:status AS VARCHAR)")
        params["status"] = status

    count_params = {k: v for k, v in params.items() if k in ("tenant_id", "pipeline_id", "status")}
    count_sql = text(
        f"SELECT COUNT(*) AS total FROM pipeline_versions pv WHERE {' AND '.join(where)}"
    )
    total = db.execute(count_sql, count_params).scalar() or 0

    sql = text(
        f"""
        SELECT pv.id, pv.tenant_id, pv.pipeline_id, pv.version, pv.status, pv.dag_spec, pv.created_at,
               p.name AS pipeline_name
        FROM pipeline_versions pv
        LEFT JOIN pipelines p ON p.id = pv.pipeline_id
        WHERE {' AND '.join(where)}
        ORDER BY pv.created_at DESC
        LIMIT :limit OFFSET :offset
        """
    )
    rows = db.execute(sql, params).mappings().all()
    items = []
    for r in rows:
        row_dict = {
            "id": r["id"],
            "tenant_id": r["tenant_id"],
            "pipeline_id": r["pipeline_id"],
            "version": r["version"],
            "status": r["status"],
            "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
            "pipeline_name": r.get("pipeline_name"),
        }
        items.append(row_dict)
    return {"items": items, "limit": limit, "offset": offset, "total": total}


@router.get("/pipeline-versions/{pipeline_version_id}")
def get_pipeline_version(pipeline_version_id: str, db: Session = Depends(get_db)):
    row = db.execute(
        text(
            """
            SELECT pv.id, pv.tenant_id, pv.pipeline_id, pv.version, pv.status, pv.dag_spec, pv.created_at,
                   p.name AS pipeline_name
            FROM pipeline_versions pv
            LEFT JOIN pipelines p ON p.id = pv.pipeline_id
            WHERE pv.id = :id
            """
        ),
        {"id": pipeline_version_id},
    ).mappings().first()
    if row is None:
        return JSONResponse(
            status_code=404,
            content={"found": False, "reason": "pipeline_version_not_found"},
        )
    out = dict(row)
    if out.get("created_at"):
        out["created_at"] = out["created_at"].isoformat()
    if "pipeline_name" in out and out["pipeline_name"] is None:
        del out["pipeline_name"]
    return {"found": True, "pipeline_version": out}


@router.post("/pipeline-versions/{pipeline_version_id}/status", response_model=PipelineVersionOut)
def set_pipeline_version_status(pipeline_version_id: str, body: ApproveVersionIn, db: Session = Depends(get_db)):
    pv = db.get(PipelineVersion, pipeline_version_id)
    if not pv:
        raise HTTPException(404, "pipeline version not found")
    if body.status not in ("APPROVED", "DEPRECATED", "DRAFT"):
        raise HTTPException(400, "invalid status")
    pv.status = body.status
    db.commit()
    db.refresh(pv)
    return PipelineVersionOut(
        id=pv.id, tenant_id=pv.tenant_id, pipeline_id=pv.pipeline_id,
        version=pv.version, status=pv.status, dag_spec=pv.dag_spec
    )

@router.post("/runs", response_model=RunOut)
def create_run(body: RunCreate, db: Session = Depends(get_db)):
    pv = db.get(PipelineVersion, body.pipeline_version_id)
    if not pv:
        raise HTTPException(404, "pipeline version not found")
    if pv.status != "APPROVED":
        raise HTTPException(400, "pipeline version must be APPROVED to run")

    run = PipelineRun(
        tenant_id=body.tenant_id,
        pipeline_version_id=body.pipeline_version_id,
        trigger_type=body.trigger_type,
        parameters=body.parameters,
        status="QUEUED",
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return RunOut(
        id=run.id, tenant_id=run.tenant_id,
        pipeline_version_id=run.pipeline_version_id,
        status=run.status, trigger_type=run.trigger_type,
        parameters=run.parameters
    )
