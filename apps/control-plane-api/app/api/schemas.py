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


class RunClaimIn(BaseModel):
    worker_id: str
    tenant_id: Optional[str] = None

class RunCompleteIn(BaseModel):
    status: Literal["SUCCEEDED", "FAILED"]
    error_message: Optional[str] = None


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
