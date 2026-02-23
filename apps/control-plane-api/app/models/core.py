from sqlalchemy import String, DateTime, ForeignKey, JSON, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import datetime
import uuid

from app.db.base import Base


def _uuid() -> str:
    return str(uuid.uuid4())

class Tenant(Base):
    __tablename__ = "tenants"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    facilities = relationship("Facility", back_populates="tenant")
    connector_instances = relationship("ConnectorInstance", back_populates="tenant")
    pipelines = relationship("Pipeline", back_populates="tenant")

class Facility(Base):
    __tablename__ = "facilities"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("tenants.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    facility_type: Mapped[str] = mapped_column(String(50), nullable=False, default="STORE")
    timezone: Mapped[str] = mapped_column(String(80), nullable=False, default="America/New_York")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    tenant = relationship("Tenant", back_populates="facilities")

class ConnectorInstance(Base):
    __tablename__ = "connector_instances"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("tenants.id"), nullable=False)
    facility_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("facilities.id"), nullable=True)

    connector_type: Mapped[str] = mapped_column(String(80), nullable=False)  # e.g., "shopify", "csv"
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="ACTIVE")  # ACTIVE/NEEDS_REAUTH/DISABLED
    config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    secrets_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    tenant = relationship("Tenant", back_populates="connector_instances")

class Pipeline(Base):
    __tablename__ = "pipelines"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("tenants.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    tenant = relationship("Tenant", back_populates="pipelines")
    versions = relationship("PipelineVersion", back_populates="pipeline")

class PipelineVersion(Base):
    __tablename__ = "pipeline_versions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("tenants.id"), nullable=False)
    pipeline_id: Mapped[str] = mapped_column(String(36), ForeignKey("pipelines.id"), nullable=False)

    version: Mapped[str] = mapped_column(String(50), nullable=False)  # e.g., "v1"
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="DRAFT")  # DRAFT/APPROVED/DEPRECATED
    dag_spec: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    pipeline = relationship("Pipeline", back_populates="versions")

class PipelineRun(Base):
    __tablename__ = "pipeline_runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("tenants.id"), nullable=False)
    pipeline_version_id: Mapped[str] = mapped_column(String(36), ForeignKey("pipeline_versions.id"), nullable=False)

    status: Mapped[str] = mapped_column(String(30), nullable=False, default="QUEUED")  # QUEUED/RUNNING/SUCCEEDED/FAILED/CANCELLED
    trigger_type: Mapped[str] = mapped_column(String(30), nullable=False, default="manual")
    parameters: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    retry_of_run_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("pipeline_runs.id", ondelete="SET NULL"), nullable=True
    )
    root_run_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("pipeline_runs.id", ondelete="SET NULL"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    claimed_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    retry_of_run = relationship(
        "PipelineRun", remote_side=[id], foreign_keys=[retry_of_run_id], uselist=False
    )
    root_run = relationship(
        "PipelineRun", remote_side=[id], foreign_keys=[root_run_id], uselist=False
    )


class PipelineRunLog(Base):
    __tablename__ = "pipeline_run_logs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(String(36), ForeignKey("pipeline_runs.id"), nullable=False)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    level: Mapped[str] = mapped_column(Text, nullable=False, server_default="INFO")
    message: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)
