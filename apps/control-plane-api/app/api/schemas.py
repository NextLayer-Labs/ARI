from pydantic import BaseModel
from typing import Any, Optional, Literal

class TenantCreate(BaseModel):
    name: str

class TenantOut(BaseModel):
    id: str
    name: str

class FacilityCreate(BaseModel):
    tenant_id: str
    name: str
    facility_type: str = "STORE"
    timezone: str = "America/New_York"

class FacilityOut(BaseModel):
    id: str
    tenant_id: str
    name: str
    facility_type: str
    timezone: str

class ConnectorInstanceCreate(BaseModel):
    tenant_id: str
    facility_id: Optional[str] = None
    connector_type: str
    config: dict[str, Any] = {}
    secrets_ref: Optional[str] = None

class ConnectorInstanceOut(BaseModel):
    id: str
    tenant_id: str
    facility_id: Optional[str]
    connector_type: str
    status: str
    config: dict[str, Any]
    secrets_ref: Optional[str]

class PipelineCreate(BaseModel):
    tenant_id: str
    name: str
    description: Optional[str] = None

class PipelineOut(BaseModel):
    id: str
    tenant_id: str
    name: str
    description: Optional[str]

class PipelineVersionCreate(BaseModel):
    tenant_id: str
    pipeline_id: str
    version: str
    dag_spec: dict[str, Any] = {}

class PipelineVersionOut(BaseModel):
    id: str
    tenant_id: str
    pipeline_id: str
    version: str
    status: str
    dag_spec: dict[str, Any]
    created_at: Optional[str] = None  # ISO with timezone when returned from GET/list

class ApproveVersionIn(BaseModel):
    status: str  # "APPROVED" or "DEPRECATED"

class RunCreate(BaseModel):
    tenant_id: str
    pipeline_version_id: str
    trigger_type: str = "manual"
    parameters: dict[str, Any] = {}

class RunOut(BaseModel):
    id: str
    tenant_id: str
    pipeline_version_id: str
    status: str
    trigger_type: str
    parameters: dict[str, Any]
    retry_of_run_id: Optional[str] = None
    root_run_id: Optional[str] = None


class RunClaimIn(BaseModel):
    worker_id: str
    tenant_id: Optional[str] = None

class RunCompleteIn(BaseModel):
    status: Literal["SUCCEEDED", "FAILED"]
    error_message: Optional[str] = None


class RetryIn(BaseModel):
    """Optional parameters override for retry; if omitted, original run parameters are used."""
    parameters: Optional[dict[str, Any]] = None


class HeartbeatIn(BaseModel):
    worker_id: str


class ReapStaleIn(BaseModel):
    stale_after_seconds: int = 300
    limit: int = 100


class LogAppendIn(BaseModel):
    level: str = "INFO"
    message: str
    source: Optional[str] = None
    meta: Optional[dict[str, Any]] = None


class LogEntryOut(BaseModel):
    id: str
    ts: str  # ISO with timezone
    level: str
    message: str
    source: Optional[str] = None
    meta: Optional[dict[str, Any]] = None


class RunArtifactCreateIn(BaseModel):
    artifact_type: str
    payload: Any  # validated in route to be a JSON object
    source: Optional[str] = None
    meta: Optional[dict[str, Any]] = None


class RunArtifactOut(BaseModel):
    id: str
    run_id: str
    tenant_id: str
    created_at: str  # ISO with timezone
    artifact_type: str
    payload: dict[str, Any]
    source: Optional[str] = None
    meta: Optional[dict[str, Any]] = None


class RunArtifactsListOut(BaseModel):
    items: list[RunArtifactOut]
    count: int
    limit: int


class RawIngestCreateIn(BaseModel):
    facility_id: str
    provider: str
    mapping_version: Optional[str] = None
    as_of: Optional[str] = None
    payload: Any  # validated in route to be a JSON object


class RawIngestOut(BaseModel):
    id: str
    run_id: str
    tenant_id: str
    facility_id: str
    provider: str
    mapping_version: Optional[str] = None
    fetched_at: str
    as_of: Optional[str] = None
    payload: dict[str, Any]


class InventoryItemUpsert(BaseModel):
    sku: str
    on_hand: int
    available: Optional[int] = None
    reserved: Optional[int] = None
    source_ref: Optional[str] = None


class InventoryItemsUpsertIn(BaseModel):
    facility_id: str
    source_provider: str
    source_run_id: str
    as_of: Optional[str] = None
    items: list[InventoryItemUpsert]


class ReturnItemUpsert(BaseModel):
    return_id: str
    order_id: Optional[str] = None
    sku: str
    quantity: int
    status: str
    reason_code: Optional[str] = None
    created_at_source: Optional[str] = None
    updated_at_source: Optional[str] = None
    received_at: Optional[str] = None
    processed_at: Optional[str] = None
    disposition: Optional[str] = None


class ReturnItemsUpsertIn(BaseModel):
    facility_id: str
    source_provider: str
    source_run_id: str
    items: list[ReturnItemUpsert]
