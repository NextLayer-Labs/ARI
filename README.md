# NextLayer MVP Documentation

**Version:** 0.1.0  
**Last Updated:** February 2026

This document provides comprehensive documentation for the NextLayer MVP codebase, covering architecture, setup, API usage, and development workflows. The audience includes the founding team and future engineers joining the project.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Repository Structure](#repository-structure)
3. [Control Plane API](#control-plane-api)
4. [Data Plane Worker](#data-plane-worker)
5. [Admin Dashboard](#admin-dashboard)
6. [Database Schema](#database-schema)
7. [Timezone Handling](#timezone-handling)
8. [Local Development Setup](#local-development-setup)
9. [Verification Runbook](#verification-runbook)
10. [API Reference](#api-reference)
11. [Status & Next Steps](#status--next-steps)

---

## Architecture Overview

NextLayer MVP is a monorepo implementing a control plane/data plane architecture for pipeline execution. The system consists of three main components:

### Components

1. **Control Plane API** (FastAPI)
   - Centralized state management
   - Exposes REST APIs for registry objects and run queue
   - Manages pipeline run lifecycle
   - Stores all system state in PostgreSQL

2. **Data Plane Worker** (Python)
   - Polls control plane for queued runs
   - Executes pipeline runs (currently simulated)
   - Updates run status via control plane APIs
   - Supports horizontal scaling (multiple workers)

3. **Admin Dashboard** (Next.js)
   - Operator UI for monitoring pipeline runs
   - Real-time status updates via polling
   - Filtering and run detail views

4. **Database** (PostgreSQL 16)
   - Durable state storage
   - Runs in Docker for local development
   - Timezone-aware timestamps (UTC)

### Run Lifecycle

Pipeline runs progress through the following states:

```text
QUEUED → RUNNING → SUCCEEDED/FAILED
```

- **QUEUED**: Run created, waiting for worker to claim
- **RUNNING**: Worker has claimed the run and is executing
- **SUCCEEDED**: Run completed successfully
- **FAILED**: Run failed with error message

### Concurrency Model

- Multiple workers can run simultaneously
- Workers use `FOR UPDATE SKIP LOCKED` to atomically claim runs
- Only one worker can claim a specific QUEUED run
- Workers poll at configurable intervals (default: 1.5 seconds)

---

## Repository Structure

```text
NextLayer/
├── apps/
│   ├── control-plane-api/          # FastAPI application
│   │   ├── app/
│   │   │   ├── api/                # API routes and schemas
│   │   │   │   ├── routes.py       # Registry endpoints (tenants, facilities, etc.)
│   │   │   │   ├── runs.py         # Run lifecycle endpoints
│   │   │   │   └── schemas.py      # Pydantic models
│   │   │   ├── db/                 # Database configuration
│   │   │   │   ├── base.py         # SQLAlchemy Base
│   │   │   │   ├── session.py      # Session factory
│   │   │   │   └── deps.py         # FastAPI dependencies
│   │   │   ├── models/             # SQLAlchemy ORM models
│   │   │   │   └── core.py         # All model definitions
│   │   │   ├── main.py             # FastAPI app initialization
│   │   │   └── settings.py         # Configuration management
│   │   ├── alembic/                # Database migrations
│   │   │   ├── versions/           # Migration scripts
│   │   │   └── env.py              # Alembic environment
│   │   ├── alembic.ini             # Alembic configuration
│   │   ├── requirements.txt        # Python dependencies
│   │   └── .env                    # Environment variables (local)
│   │
│   ├── data-plane-worker/          # Worker application
│   │   └── worker.py               # Main worker loop
│   │
│   └── admin-dashboard/            # Next.js dashboard
│       ├── src/
│       │   └── app/
│       │       ├── runs/
│       │       │   ├── page.tsx    # Runs list view
│       │       │   └── [id]/
│       │       │       └── page.tsx # Run detail view
│       │       ├── layout.tsx      # Root layout
│       │       └── page.tsx        # Home page
│       ├── package.json            # Node dependencies
│       └── next.config.ts          # Next.js configuration
│
├── infra/
│   └── docker-compose.yml          # PostgreSQL container setup
│
├── docs/
│   └── run-claim-complete.md       # Detailed run workflow docs
│
└── README.md                       # This file
```

---

## Control Plane API

### Overview

The Control Plane API is a FastAPI application that serves as the central state management system. It exposes REST endpoints for managing registry objects (tenants, facilities, connectors, pipelines) and the run queue.

### Setup

#### Prerequisites

- Python 3.13+ (or compatible version)
- PostgreSQL 16 (via Docker Compose)
- Virtual environment tool (venv, virtualenv, or poetry)

#### Installation

```powershell
# Navigate to control plane directory
cd apps/control-plane-api

# Create virtual environment
python -m venv venv

# Activate virtual environment
# Windows PowerShell:
.\venv\Scripts\Activate.ps1
# Linux/Mac:
# source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

#### Environment Variables

Create a `.env` file in `apps/control-plane-api/`:

```env
DATABASE_URL=postgresql+psycopg://nextlayer:nextlayer@localhost:5432/nextlayer
CORS_ORIGINS=http://127.0.0.1:3000,http://localhost:3000
```

**Variables:**
- `DATABASE_URL`: PostgreSQL connection string (required)
- `CORS_ORIGINS`: Comma-separated list of allowed origins for CORS (default: `http://127.0.0.1:3000`)

#### Database Setup

```powershell
# Ensure PostgreSQL is running (see Local Development Setup)
# From apps/control-plane-api directory:

# Run migrations
alembic upgrade head

# Verify migration status
alembic current
```

#### Running the API

```powershell
# From apps/control-plane-api directory with venv activated
uvicorn app.main:app --reload --port 8000
```

The API will be available at `http://localhost:8000`

- API docs (Swagger UI): `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`
- Health check: `http://localhost:8000/health`

### Database Models

The following SQLAlchemy models are defined in `app/models/core.py`:

#### Tenant
- `id` (UUID string, primary key)
- `name` (string, max 200 chars)
- `created_at` (timestamptz)

#### Facility
- `id` (UUID string, primary key)
- `tenant_id` (foreign key to tenants)
- `name` (string, max 200 chars)
- `facility_type` (string, default: "STORE")
- `timezone` (string, default: "America/New_York")
- `created_at` (timestamptz)

#### ConnectorInstance
- `id` (UUID string, primary key)
- `tenant_id` (foreign key to tenants)
- `facility_id` (foreign key to facilities, nullable)
- `connector_type` (string, e.g., "shopify", "csv")
- `status` (string: ACTIVE/NEEDS_REAUTH/DISABLED)
- `config` (JSON)
- `secrets_ref` (string, nullable)
- `created_at` (timestamptz)

#### Pipeline
- `id` (UUID string, primary key)
- `tenant_id` (foreign key to tenants)
- `name` (string, max 200 chars)
- `description` (text, nullable)
- `created_at` (timestamptz)

#### PipelineVersion
- `id` (UUID string, primary key)
- `tenant_id` (foreign key to tenants)
- `pipeline_id` (foreign key to pipelines)
- `version` (string, e.g., "v1")
- `status` (string: DRAFT/APPROVED/DEPRECATED)
- `dag_spec` (JSON)
- `created_at` (timestamptz)

#### PipelineRun
- `id` (UUID string, primary key)
- `tenant_id` (foreign key to tenants)
- `pipeline_version_id` (foreign key to pipeline_versions)
- `status` (string: QUEUED/RUNNING/SUCCEEDED/FAILED/CANCELLED)
- `trigger_type` (string, default: "manual")
- `parameters` (JSON)
- `retry_of_run_id` (UUID string, nullable, FK to pipeline_runs.id) — set when run was created via Retry
- `root_run_id` (UUID string, nullable, FK to pipeline_runs.id) — root of retry chain for grouping
- `created_at` (timestamptz)
- `started_at` (timestamptz, nullable)
- `claimed_at` (timestamptz, nullable)
- `claimed_by` (string, nullable)
- `heartbeat_at` (timestamptz, nullable)
- `finished_at` (timestamptz, nullable)
- `error_message` (text, nullable)
- `updated_at` (timestamptz)

### Key Endpoints

#### Registry Endpoints (`/api/*`)

- `POST /api/tenants` - Create tenant
- `POST /api/facilities` - Create facility
- `POST /api/connector-instances` - Create connector instance
- `POST /api/pipelines` - Create pipeline
- `POST /api/pipeline-versions` - Create pipeline version (status: DRAFT)
- `POST /api/pipeline-versions/{id}/status` - Update version status (APPROVED/DEPRECATED/DRAFT)
- `GET /api/pipeline-versions` - List pipeline versions (filters: tenant_id, pipeline_id, status; limit/offset)
- `GET /api/pipeline-versions/{id}` - Get pipeline version by ID (includes dag_spec)
- `GET /api/pipelines` - List pipelines (optional tenant_id; limit/offset)

#### Run Lifecycle Endpoints (`/api/runs/*`)

- `POST /api/runs` - Create QUEUED run (requires APPROVED pipeline version)
- `POST /api/runs/claim` - Atomically claim a QUEUED run (SKIP LOCKED)
- `POST /api/runs/{id}/complete` - Transition RUNNING → SUCCEEDED/FAILED
- `POST /api/runs/{id}/cancel` - Cancel run (QUEUED or RUNNING → CANCELLED; writes WARN log)
- `POST /api/runs/{id}/retry` - Create new QUEUED run from FAILED/CANCELLED (optional body: `{ "parameters": { ... } }`)
- `POST /api/runs/{id}/heartbeat` - Update heartbeat_at for RUNNING run (body: `{ "worker_id": "..." }`); 409 if not RUNNING or worker_mismatch
- `POST /api/runs/reap-stale` - Mark stale RUNNING runs as FAILED (body: `{ "stale_after_seconds": 300, "limit": 100 }` optional)
- `GET /api/runs/{id}` - Get run details (includes retry_of_run_id, root_run_id, heartbeat_at when set)
- `GET /api/runs` - List runs with filters and pagination (query params: tenant_id, status, retry_of_run_id; status includes CANCELLED)

**Retry lineage:** Runs created via Retry store `retry_of_run_id` (parent run) and `root_run_id` (root of the retry chain). The dashboard run detail page shows “Retry of” (link to parent) and “Retries” (child runs). Use `GET /api/runs?retry_of_run_id=<run_id>` to list child retries.

**Heartbeats and stale reaper:** While a run is RUNNING, the worker calls `POST /api/runs/{id}/heartbeat` periodically (configurable via `HEARTBEAT_SECONDS`). Only the claiming worker may heartbeat (409 if status is not RUNNING or worker_mismatch). The run detail page shows `heartbeat_at`. To recover runs left RUNNING by a crashed worker, call `POST /api/runs/reap-stale` with optional body `{ "stale_after_seconds": 300, "limit": 100 }`; it marks RUNNING runs with no heartbeat within the window as FAILED and writes a WARN log.

### Dynamic WHERE Clause Implementation

The `GET /api/runs` endpoint uses dynamic WHERE clause construction to avoid PostgreSQL NULL parameter type ambiguity. Instead of using SQLAlchemy's ORM with optional filters (which can cause type inference issues), the endpoint builds SQL strings dynamically:

```python
where = ["1=1"]
params: dict = {"limit": limit, "offset": offset}

if tenant_id is not None:
    where.append("tenant_id = :tenant_id")
    params["tenant_id"] = str(tenant_id)

if status is not None:
    where.append("status = CAST(:status AS VARCHAR)")
    params["status"] = status
```

This approach ensures type safety and avoids NULL parameter ambiguity when filters are optional.

### CORS Configuration

CORS is configured to allow requests from the admin dashboard (default: `http://localhost:3000`). Configure allowed origins via the `CORS_ORIGINS` environment variable (comma-separated).

### Alembic Migrations

Database schema changes are managed via Alembic migrations:

```powershell
# Create a new migration (after model changes)
alembic revision --autogenerate -m "description"

# Apply migrations
alembic upgrade head

# Rollback one migration
alembic downgrade -1

# View migration history
alembic history

# View current revision
alembic current
```

**Migration Files:**
- `f1e1d445c1d4_init_core_tables.py` - Initial schema
- `3f1739d6108c_add_pipeline_run_lifecycle_columns.py` - Added claimed_at, claimed_by, heartbeat_at, error_message, updated_at
- `a1b2c3d4e5f6_pipeline_runs_timestamptz.py` - Converted timestamps to timestamptz
- `b2c3d4e5f6a7_add_pipeline_run_logs.py` - pipeline_run_logs table
- `c4d5e6f7a8b9_add_retry_lineage_columns.py` - retry_of_run_id, root_run_id on pipeline_runs (indexes + FKs)

---

## Data Plane Worker

### Overview

The Data Plane Worker is a Python script that polls the Control Plane API for queued runs, executes them (currently simulated), and updates their status. Multiple workers can run simultaneously, with PostgreSQL's `SKIP LOCKED` ensuring only one worker claims each run.

### Setup

#### Prerequisites

- Python 3.13+ (or compatible version)
- Control Plane API running and accessible
- Virtual environment (optional but recommended)

#### Installation

```powershell
# Navigate to worker directory
cd apps/data-plane-worker

# Create virtual environment (optional)
python -m venv venv
.\venv\Scripts\Activate.ps1  # Windows PowerShell

# Install dependencies (if using venv, httpx should be installed globally or in venv)
pip install httpx
```

**Note:** The worker uses `httpx` for HTTP requests. Ensure it's installed in your Python environment.

#### Environment Variables

- `CP_BASE` - Control Plane API base URL (default: `http://localhost:8000`)
- `POLL_SECONDS` - Polling interval in seconds (default: `1.5`)
- `WORKER_ID` - Worker identifier (default: `{hostname}:{pid}`)
- `TENANT_ID` - Optional tenant filter (only claim runs for this tenant)
- `HEARTBEAT_SECONDS` - How often to send heartbeat while a run is RUNNING (default: `10`)
- `SIMULATE_SECONDS` - Duration of simulated work (default: `0.5`; set higher e.g. `20` to test heartbeats)

#### Running the Worker

```powershell
# From apps/data-plane-worker directory
# Set environment variables (PowerShell)
$env:CP_BASE = "http://localhost:8000"
$env:POLL_SECONDS = "1.5"
# $env:WORKER_ID = "dpw-1"  # Optional
# $env:TENANT_ID = "tenant-uuid"  # Optional

# Run worker
python worker.py
```

### Worker Loop

The worker implements the following loop:

1. **Claim Run**: `POST /api/runs/claim`
   - Returns `{"claimed": false}` if no QUEUED runs available
   - Returns `{"claimed": true, "run": {...}, "pipeline_version": {...}}` if a run was claimed

2. **Execute Run** (simulated):
   - Reads `dag_spec` from pipeline version
   - Runs for `SIMULATE_SECONDS` (default 0.5s), sending `POST /api/runs/{id}/heartbeat` every `HEARTBEAT_SECONDS` (default 10s)
   - If heartbeat returns 409 (run cancelled/reaped or worker_mismatch), stops without calling complete
   - Handles exceptions

3. **Complete Run**: `POST /api/runs/{id}/complete`
   - Status: `SUCCEEDED` or `FAILED`
   - Error message included if failed

4. **Sleep**: Waits `POLL_SECONDS` before next iteration

### Concurrency

- Multiple workers can run simultaneously
- Each worker polls independently
- `FOR UPDATE SKIP LOCKED` ensures atomic claim (only one worker gets each QUEUED run)
- Workers can be scaled horizontally for higher throughput

### Error Handling

- Network errors are logged and the worker continues polling
- Execution exceptions are caught and the run is marked as FAILED with error message
- Worker continues running after errors (does not crash)

---

## Admin Dashboard

### Overview

The Admin Dashboard is a Next.js application providing a web UI for operators to monitor pipeline runs in real-time. It polls the Control Plane API every ~2 seconds to display run statuses.

### Setup

#### Prerequisites

- Node.js 20+ (or compatible version)
- npm, yarn, pnpm, or bun
- Control Plane API running and accessible

#### Installation

```powershell
# Navigate to dashboard directory
cd apps/admin-dashboard

# Install dependencies (using pnpm as configured)
pnpm install

# Or using npm
npm install
```

#### Environment Variables

Create a `.env.local` file (optional):

```env
NEXT_PUBLIC_CP_BASE=http://localhost:8000
```

**Variables:**
- `NEXT_PUBLIC_CP_BASE` - Control Plane API base URL (default: `http://localhost:8000`)

#### Running the Dashboard

```powershell
# From apps/admin-dashboard directory
pnpm dev
# Or
npm run dev
```

The dashboard will be available at `http://localhost:3000`

### Pages

#### `/runs` - Runs List View

- Displays table of pipeline runs with:
  - Created timestamp (local timezone)
  - Status badge (QUEUED/RUNNING/SUCCEEDED/FAILED/CANCELLED)
  - Run ID (truncated, clickable link to detail)
  - Claimed by (worker ID)
  - Pipeline version ID (truncated)
  - Error message (if FAILED)
  - **Actions**: Cancel (QUEUED/RUNNING), **Retry** (FAILED/CANCELLED) — Retry opens a modal to optionally override parameters (JSON object) before creating the new run
- Status filter dropdown (All, QUEUED, RUNNING, SUCCEEDED, FAILED, CANCELLED)
- Auto-refreshes every ~2 seconds
- Pagination info displayed (limit/offset/count)

#### `/runs/[id]` - Run Detail View

- Displays full run details:
  - All run fields (ID, status, tenant, pipeline version, etc.)
  - **Retry lineage**: If this run was created via Retry, shows “Retry of: \<link to parent run\>”; a “Retries” section lists child runs (created by retrying this run) with links to each
  - Timestamps formatted in local timezone
  - Parameters JSON (if present)
  - Error message (if FAILED)
- **Actions**: Cancel (QUEUED/RUNNING), **Retry** (FAILED/CANCELLED) — Retry opens a modal with the current run’s parameters (editable JSON); you can change them before creating the new run; on success you are redirected to the new run page
- Link back to runs list
- Fetches data on mount; polls status/logs until terminal; fetches child retries for lineage

#### `/pipeline-versions` - Pipeline Versions List

- Table of pipeline versions with version ID, status badge, version string, pipeline (name or ID), tenant ID, created_at
- Filters: status (All/DRAFT/APPROVED/DEPRECATED), tenant_id, pipeline_id (apply on submit)
- Pagination: Prev/Next with limit/offset and total
- Per-row actions: Approve (when DRAFT), **Run** and Deprecate (when APPROVED); buttons disable while in-flight and list refreshes on success

#### `/pipeline-versions/[id]` - Pipeline Version Detail

- Full version details including dag_spec (collapsible JSON)
- Back link to list; same Approve/Deprecate actions as list page; **Trigger run** when APPROVED

#### How to trigger a run from the UI

You can create a manual run (QUEUED) from the dashboard without using PowerShell. On the **Pipeline Versions** list (`/pipeline-versions`) or on a version’s detail page (`/pipeline-versions/[id]`), for any **APPROVED** version click **Run** (list) or **Trigger run** (detail). A modal opens: enter **parameters** as a JSON object (e.g. `{}` or `{"key": "value"}`). Parameters must be valid JSON and must be an object (not an array or primitive). Click **Create run**; on success you are redirected to `/runs/[id]` where you can watch status and logs. The worker will claim and execute the run as usual.

#### Retry with parameter override

For a **FAILED** or **CANCELLED** run, click **Retry** on the runs list or run detail page. A modal opens with the current run’s parameters (pretty-printed JSON). You can leave them as-is or edit to override (must be a valid JSON object). Click **Create retry**; the API creates a new QUEUED run with `trigger_type: "retry"` and the given parameters, and you are redirected to `/runs/[new_run_id]`. Retry lineage (`retry_of_run_id`, `root_run_id`) is set as before.

### Features

- **Real-time Updates**: Polls Control Plane API every 2 seconds
- **Status Filtering**: Filter runs by status
- **Timezone Handling**: Converts UTC timestamps to local display
- **Error Display**: Shows error messages for failed runs
- **Responsive Design**: Works on desktop and mobile
- **Dark Mode Support**: Uses Tailwind CSS dark mode classes

### Technology Stack

- **Framework**: Next.js 16.1.4 (App Router)
- **UI**: React 19.2.3
- **Styling**: Tailwind CSS 4
- **TypeScript**: TypeScript 5

---

## Database Schema

### Overview

PostgreSQL 16 is used as the durable state store. All timestamps are stored as `timestamptz` (timezone-aware) and interpreted as UTC.

### Tables

See [Database Models](#database-models) section for detailed field descriptions.

### Relationships

```
Tenant
  ├── Facilities (1:N)
  ├── ConnectorInstances (1:N)
  └── Pipelines (1:N)
      └── PipelineVersions (1:N)
          └── PipelineRuns (1:N)
```

### Indexes

- Primary keys on all tables (`id`)
- Foreign key indexes (automatically created by PostgreSQL)
- Consider adding indexes on frequently queried columns:
  - `pipeline_runs.status`
  - `pipeline_runs.created_at`
  - `pipeline_runs.tenant_id`

### Connection String Format

```
postgresql+psycopg://{user}:{password}@{host}:{port}/{database}
```

Example:
```
postgresql+psycopg://nextlayer:nextlayer@localhost:5432/nextlayer
```

---

## Timezone Handling

### Problem

Initially, timestamps were stored as naive `timestamp` (without timezone) in PostgreSQL. This caused display issues in the dashboard, showing times 4-5 hours off due to timezone conversion ambiguity.

### Solution

All timestamp columns were migrated to `timestamptz` (timezone-aware):

1. **Database**: Columns use `timestamptz` type
2. **SQLAlchemy**: Models use `DateTime(timezone=True)`
3. **API**: Returns ISO 8601 strings with timezone offset (e.g., `2026-02-11T12:00:00+00:00`)
4. **UI**: JavaScript `Date` objects parse ISO strings and convert to local timezone for display

### Migration

Migration `a1b2c3d4e5f6_pipeline_runs_timestamptz.py` converted existing columns:

```sql
ALTER TABLE pipeline_runs
  ALTER COLUMN created_at TYPE timestamptz USING created_at AT TIME ZONE 'UTC',
  ALTER COLUMN started_at TYPE timestamptz USING started_at AT TIME ZONE 'UTC',
  ALTER COLUMN finished_at TYPE timestamptz USING finished_at AT TIME ZONE 'UTC'
```

Existing values were interpreted as UTC during migration.

### Best Practices

- **Storage**: Always store timestamps as UTC (`timestamptz`)
- **API**: Return ISO 8601 strings with timezone offset
- **UI**: Convert to local timezone for display only
- **PostgreSQL**: Runs in UTC timezone (`Etc/UTC`)

---

## Local Development Setup

### Prerequisites

- Docker Desktop (or Docker Engine + Docker Compose)
- Python 3.13+ (or compatible)
- Node.js 20+ (or compatible)
- PowerShell (Windows) or bash (Linux/Mac)

### Step-by-Step Setup

#### 1. Start PostgreSQL

```powershell
# From repository root
docker compose -f infra/docker-compose.yml up -d

# Verify container is running
docker ps | Select-String "nextlayer-postgres"
```

**Container Details:**
- Container name: `nextlayer-postgres`
- Port: `5432`
- User: `nextlayer`
- Password: `nextlayer`
- Database: `nextlayer`

#### 2. Setup Control Plane API

```powershell
# Navigate to control plane directory
cd apps/control-plane-api

# Create and activate virtual environment
python -m venv venv
.\venv\Scripts\Activate.ps1  # Windows PowerShell
# source venv/bin/activate  # Linux/Mac

# Install dependencies
pip install -r requirements.txt

# Set environment variables
$env:DATABASE_URL = "postgresql+psycopg://nextlayer:nextlayer@localhost:5432/nextlayer"
$env:CORS_ORIGINS = "http://127.0.0.1:3000,http://localhost:3000"

# Run migrations
alembic upgrade head

# Start API server
uvicorn app.main:app --reload --port 8000
```

**Verify:** Open `http://localhost:8000/docs` in browser

#### 3. Setup Data Plane Worker

```powershell
# Open a new terminal/PowerShell window
# Navigate to worker directory
cd apps/data-plane-worker

# Activate virtual environment (if using one)
# .\venv\Scripts\Activate.ps1  # Windows PowerShell

# Set environment variables
$env:CP_BASE = "http://localhost:8000"
$env:POLL_SECONDS = "1.5"
# $env:WORKER_ID = "dpw-1"  # Optional

# Run worker
python worker.py
```

**Verify:** Worker should print "No queued runs. Sleeping..." if no runs exist

#### 4. Setup Admin Dashboard

```powershell
# Open a new terminal/PowerShell window
# Navigate to dashboard directory
cd apps/admin-dashboard

# Install dependencies
pnpm install
# Or: npm install

# Optional: Set environment variable
# $env:NEXT_PUBLIC_CP_BASE = "http://localhost:8000"

# Start development server
pnpm dev
# Or: npm run dev
```

**Verify:** Open `http://localhost:3000/runs` in browser

### Quick Start Script (PowerShell)

Save as `start-local.ps1` in repository root:

```powershell
# Start PostgreSQL
Write-Host "Starting PostgreSQL..." -ForegroundColor Green
docker compose -f infra/docker-compose.yml up -d

# Wait for PostgreSQL to be ready
Start-Sleep -Seconds 3

# Start Control Plane API (in background)
Write-Host "Starting Control Plane API..." -ForegroundColor Green
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd apps/control-plane-api; `$env:DATABASE_URL='postgresql+psycopg://nextlayer:nextlayer@localhost:5432/nextlayer'; `$env:CORS_ORIGINS='http://127.0.0.1:3000,http://localhost:3000'; python -m venv venv; .\venv\Scripts\Activate.ps1; pip install -r requirements.txt; alembic upgrade head; uvicorn app.main:app --reload --port 8000"

# Start Worker (in background)
Write-Host "Starting Worker..." -ForegroundColor Green
Start-Sleep -Seconds 5
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd apps/data-plane-worker; `$env:CP_BASE='http://localhost:8000'; `$env:POLL_SECONDS='1.5'; python worker.py"

# Start Dashboard (in background)
Write-Host "Starting Dashboard..." -ForegroundColor Green
Start-Sleep -Seconds 2
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd apps/admin-dashboard; pnpm dev"

Write-Host "All services started!" -ForegroundColor Green
Write-Host "API: http://localhost:8000/docs" -ForegroundColor Cyan
Write-Host "Dashboard: http://localhost:3000/runs" -ForegroundColor Cyan
```

---

## Verification Runbook

This section provides step-by-step commands to verify the system is working correctly.

### Prerequisites

- All services running (PostgreSQL, Control Plane API, Worker, Dashboard)
- PowerShell (Windows) or bash (Linux/Mac)

### Step 1: Create Test Data

#### Create a Tenant

```powershell
$tenantBody = @{
    name = "Test Tenant"
} | ConvertTo-Json

$tenant = Invoke-RestMethod -Method Post -Uri "http://localhost:8000/api/tenants" -ContentType "application/json" -Body $tenantBody
$tenantId = $tenant.id
Write-Host "Created tenant: $tenantId" -ForegroundColor Green
```

#### Create a Pipeline

```powershell
$pipelineBody = @{
    tenant_id = $tenantId
    name = "Test Pipeline"
    description = "A test pipeline"
} | ConvertTo-Json

$pipeline = Invoke-RestMethod -Method Post -Uri "http://localhost:8000/api/pipelines" -ContentType "application/json" -Body $pipelineBody
$pipelineId = $pipeline.id
Write-Host "Created pipeline: $pipelineId" -ForegroundColor Green
```

#### Create a Pipeline Version (DRAFT)

```powershell
$versionBody = @{
    tenant_id = $tenantId
    pipeline_id = $pipelineId
    version = "v1"
    dag_spec = @{
        steps = @("step1", "step2")
    }
} | ConvertTo-Json

$version = Invoke-RestMethod -Method Post -Uri "http://localhost:8000/api/pipeline-versions" -ContentType "application/json" -Body $versionBody
$versionId = $version.id
Write-Host "Created pipeline version: $versionId (status: $($version.status))" -ForegroundColor Green
```

#### Approve Pipeline Version

```powershell
$approveBody = @{
    status = "APPROVED"
} | ConvertTo-Json

$approvedVersion = Invoke-RestMethod -Method Post -Uri "http://localhost:8000/api/pipeline-versions/$versionId/status" -ContentType "application/json" -Body $approveBody
Write-Host "Approved pipeline version: $($approvedVersion.status)" -ForegroundColor Green
```

**Quick seed for Pipeline Versions UI (dashboard):** To test the Pipeline Versions list and Approve/Deprecate UI at `http://localhost:3000/pipeline-versions`, run only the "Create a Tenant", "Create a Pipeline", and "Create a Pipeline Version (DRAFT)" blocks above (do not approve). Then open `/pipeline-versions` and use the Approve button; optionally Deprecate afterward.

### Step 2: Create a Run

```powershell
$runBody = @{
    tenant_id = $tenantId
    pipeline_version_id = $versionId
    trigger_type = "manual"
    parameters = @{
        test_param = "test_value"
    }
} | ConvertTo-Json

$run = Invoke-RestMethod -Method Post -Uri "http://localhost:8000/api/runs" -ContentType "application/json" -Body $runBody
$runId = $run.id
Write-Host "Created run: $runId (status: $($run.status))" -ForegroundColor Green
```

### Step 3: Verify Run Lifecycle

#### Check Run Status (should be QUEUED initially)

```powershell
$runDetail = Invoke-RestMethod -Method Get -Uri "http://localhost:8000/api/runs/$runId"
Write-Host "Run status: $($runDetail.run.status)" -ForegroundColor Cyan
```

#### Watch Worker Claim and Execute

The worker should automatically:
1. Claim the run (status → RUNNING)
2. Execute it (simulated 0.5s sleep)
3. Complete it (status → SUCCEEDED)

Monitor the worker terminal output. You should see:
```
Claimed run {runId} -> RUNNING
Completed run {runId} -> SUCCEEDED
```

#### Verify Final Status

```powershell
$finalRun = Invoke-RestMethod -Method Get -Uri "http://localhost:8000/api/runs/$runId"
Write-Host "Final status: $($finalRun.run.status)" -ForegroundColor Green
Write-Host "Started at: $($finalRun.run.started_at)" -ForegroundColor Cyan
Write-Host "Finished at: $($finalRun.run.finished_at)" -ForegroundColor Cyan
Write-Host "Claimed by: $($finalRun.run.claimed_by)" -ForegroundColor Cyan
```

### Step 4: Verify Dashboard

1. Open `http://localhost:3000/runs` in browser
2. Verify the run appears in the table
3. Check status badge shows "SUCCEEDED"
4. Click on the run ID to view detail page
5. Verify all timestamps display correctly (local timezone)

### Step 5: Database Verification

```powershell
# Connect to PostgreSQL container
docker exec -it nextlayer-postgres psql -U nextlayer -d nextlayer

# In psql prompt:
SELECT id, status, claimed_by, started_at, finished_at, error_message 
FROM pipeline_runs 
ORDER BY created_at DESC 
LIMIT 5;

# Exit psql
\q
```

### Step 6: Test Filtering

```powershell
# List only QUEUED runs
Invoke-RestMethod -Method Get -Uri "http://localhost:8000/api/runs?status=QUEUED"

# List only SUCCEEDED runs
Invoke-RestMethod -Method Get -Uri "http://localhost:8000/api/runs?status=SUCCEEDED"

# List runs for specific tenant
Invoke-RestMethod -Method Get -Uri "http://localhost:8000/api/runs?tenant_id=$tenantId"
```

### Step 7: Test Error Handling

Create a run and manually fail it:

```powershell
# Claim a run manually
$claimBody = @{
    worker_id = "manual-test"
} | ConvertTo-Json

$claimed = Invoke-RestMethod -Method Post -Uri "http://localhost:8000/api/runs/claim" -ContentType "application/json" -Body $claimBody

if ($claimed.claimed) {
    $failedRunId = $claimed.run.id
    
    # Complete with FAILED status
    $failBody = @{
        status = "FAILED"
        error_message = "Manual test failure"
    } | ConvertTo-Json
    
    Invoke-RestMethod -Method Post -Uri "http://localhost:8000/api/runs/$failedRunId/complete" -ContentType "application/json" -Body $failBody
    
    # Verify
    $failedRun = Invoke-RestMethod -Method Get -Uri "http://localhost:8000/api/runs/$failedRunId"
    Write-Host "Failed run status: $($failedRun.run.status)" -ForegroundColor Red
    Write-Host "Error message: $($failedRun.run.error_message)" -ForegroundColor Red
}
```

### Step 8: Run actions (Cancel, Retry) and worker resilience

**Cancel a run (QUEUED or RUNNING):**

1. Seed a tenant/pipeline/version, approve it, and trigger a run from the dashboard (or create one via API).
2. While the run is QUEUED or RUNNING, open `/runs` or `/runs/[id]` and click **Cancel**.
3. Confirm the run transitions to **CANCELLED**, `finished_at` is set, and a WARN log entry "Run cancelled" (source: control-plane) appears in the run logs.
4. If the worker had claimed the run and then you cancelled it, the worker should log "complete skipped: run ... is no longer RUNNING" and continue polling (no crash).

**Retry a run (FAILED or CANCELLED):**

1. From a FAILED or CANCELLED run, click **Retry** on the list or detail page.
2. Confirm a new QUEUED run is created and the UI redirects to `/runs/[new_run_id]`.
3. Confirm the new run executes (worker claims and completes) and its logs show "Retry of \<old_run_id\>" (source: control-plane).

**Worker resilience (optional):**

- Stop the control plane briefly while a run is RUNNING; restart it. The worker retries the `/complete` call with backoff; once the API is back, the run should complete or you can cancel it. The worker process should not crash.

### Step 9: Heartbeats and stale reaper

**Heartbeat updates during RUNNING:**

1. Set worker env `$env:SIMULATE_SECONDS = "20"` and `$env:HEARTBEAT_SECONDS = "5"` so the worker runs long enough to send heartbeats.
2. Trigger a run from the dashboard; while it is RUNNING, call `GET /api/runs/{id}` and confirm `heartbeat_at` advances (or refresh the run detail page and check the Heartbeat at field).

**Stale reaper (crashed worker):**

1. Trigger a run so the worker claims it (status RUNNING).
2. Kill the worker (Ctrl+C in Terminal C).
3. Wait longer than `stale_after_seconds` (e.g. 10 seconds for a quick test).
4. Call the reaper:  
   `Invoke-RestMethod -Method Post -Uri "http://localhost:8000/api/runs/reap-stale" -ContentType "application/json" -Body '{"stale_after_seconds": 10}'`
5. Confirm the run is now FAILED, `finished_at` is set, `error_message` contains "Stale: no heartbeat...", and run logs include WARN "Run marked stale by reaper" (source: control-plane).
6. Restart the worker; it should continue claiming other runs normally.

---

## API Reference

### Registry Endpoints

#### POST /api/tenants

Create a new tenant.

**Request Body:**
```json
{
  "name": "Tenant Name"
}
```

**Response:** `200 OK`
```json
{
  "id": "uuid",
  "name": "Tenant Name"
}
```

#### POST /api/pipelines

Create a new pipeline.

**Request Body:**
```json
{
  "tenant_id": "uuid",
  "name": "Pipeline Name",
  "description": "Optional description"
}
```

**Response:** `200 OK`
```json
{
  "id": "uuid",
  "tenant_id": "uuid",
  "name": "Pipeline Name",
  "description": "Optional description"
}
```

#### POST /api/pipeline-versions

Create a new pipeline version (status: DRAFT).

**Request Body:**
```json
{
  "tenant_id": "uuid",
  "pipeline_id": "uuid",
  "version": "v1",
  "dag_spec": {}
}
```

**Response:** `200 OK`
```json
{
  "id": "uuid",
  "tenant_id": "uuid",
  "pipeline_id": "uuid",
  "version": "v1",
  "status": "DRAFT",
  "dag_spec": {}
}
```

#### POST /api/pipeline-versions/{id}/status

Update pipeline version status.

**Request Body:**
```json
{
  "status": "APPROVED"  // or "DEPRECATED" or "DRAFT"
}
```

**Response:** `200 OK`
```json
{
  "id": "uuid",
  "tenant_id": "uuid",
  "pipeline_id": "uuid",
  "version": "v1",
  "status": "APPROVED",
  "dag_spec": {}
}
```

### Run Lifecycle Endpoints

#### POST /api/runs

Create a new pipeline run (status: QUEUED).

**Request Body:**
```json
{
  "tenant_id": "uuid",
  "pipeline_version_id": "uuid",
  "trigger_type": "manual",
  "parameters": {}
}
```

**Response:** `200 OK`
```json
{
  "id": "uuid",
  "tenant_id": "uuid",
  "pipeline_version_id": "uuid",
  "status": "QUEUED",
  "trigger_type": "manual",
  "parameters": {}
}
```

**Errors:**
- `400 Bad Request`: Pipeline version must be APPROVED
- `404 Not Found`: Pipeline version not found

#### POST /api/runs/claim

Atomically claim a QUEUED run (SKIP LOCKED).

**Request Body:**
```json
{
  "worker_id": "worker-identifier",
  "tenant_id": "uuid"  // optional
}
```

**Response:** `200 OK`
```json
{
  "claimed": true,
  "run": {
    "id": "uuid",
    "tenant_id": "uuid",
    "pipeline_version_id": "uuid",
    "status": "RUNNING",
    "started_at": "2026-02-11T12:00:00+00:00",
    "claimed_at": "2026-02-11T12:00:00+00:00",
    "claimed_by": "worker-identifier",
    // ... other fields
  },
  "pipeline_version": {
    "id": "uuid",
    "status": "APPROVED",
    "dag_spec": {}
  }
}
```

If no QUEUED runs available:
```json
{
  "claimed": false
}
```

#### POST /api/runs/{id}/complete

Complete a RUNNING run (transition to SUCCEEDED or FAILED).

**Request Body:**
```json
{
  "status": "SUCCEEDED",  // or "FAILED"
  "error_message": "Optional error message"  // required if status is FAILED
}
```

**Response:** `200 OK`
```json
{
  "ok": true,
  "run": {
    "id": "uuid",
    "status": "SUCCEEDED",
    "finished_at": "2026-02-11T12:00:05+00:00",
    // ... other fields
  }
}
```

**Errors:**
- `409 Conflict`: Run not RUNNING or not found

#### GET /api/runs/{id}

Get run details.

**Response:** `200 OK`
```json
{
  "found": true,
  "run": {
    "id": "uuid",
    "tenant_id": "uuid",
    "pipeline_version_id": "uuid",
    "status": "SUCCEEDED",
    "trigger_type": "manual",
    "parameters": {},
    "claimed_by": "worker-identifier",
    "claimed_at": "2026-02-11T12:00:00+00:00",
    "started_at": "2026-02-11T12:00:00+00:00",
    "finished_at": "2026-02-11T12:00:05+00:00",
    "error_message": null,
    "created_at": "2026-02-11T12:00:00+00:00",
    "updated_at": "2026-02-11T12:00:05+00:00"
  }
}
```

**Response:** `404 Not Found`
```json
{
  "found": false,
  "reason": "run_not_found"
}
```

#### GET /api/runs

List runs with filters and pagination.

**Query Parameters:**
- `tenant_id` (optional): Filter by tenant ID
- `status` (optional): Filter by status (QUEUED, RUNNING, SUCCEEDED, FAILED)
- `limit` (optional, default: 20, max: 100): Number of results per page
- `offset` (optional, default: 0): Pagination offset

**Example:**
```
GET /api/runs?status=QUEUED&limit=10&offset=0
```

**Response:** `200 OK`
```json
{
  "items": [
    {
      "id": "uuid",
      "tenant_id": "uuid",
      "pipeline_version_id": "uuid",
      "status": "QUEUED",
      // ... other fields
    }
  ],
  "limit": 20,
  "offset": 0,
  "count": 1
}
```

---

## Status & Next Steps

### Current Completion Status

✅ **Completed Features:**

1. **Run Lifecycle**
   - Create QUEUED runs
   - Atomic claim with SKIP LOCKED
   - Complete runs (SUCCEEDED/FAILED)
   - Full lifecycle tracking (claimed_at, claimed_by, heartbeat_at, etc.)

2. **Worker Execution**
   - Polling mechanism
   - Claim/execute/complete loop
   - Error handling
   - Multi-worker support

3. **Dashboard List View**
   - Real-time polling (~2 seconds)
   - Status filtering
   - Run table with key fields
   - Error message display

4. **Timezone Correctness**
   - All timestamps stored as timestamptz (UTC)
   - API returns ISO 8601 with timezone offset
   - UI converts to local timezone for display

5. **Run Detail View**
   - Full run details page (`/runs/[id]`)
   - All fields displayed
   - Parameters JSON view
   - Error message display

### Recommended Next Steps

#### High Priority

1. **Pipeline/Pipeline Version UI**
   - List pipelines and versions
   - Approve/deprecate versions via UI
   - View DAG specs
   - Create new pipelines/versions

2. **Connector Instance UI**
   - Register connector instances
   - View connector status
   - Manage connector configuration
   - Test connector connectivity

3. **Enhanced Run Detail View**
   - Add real-time updates (polling)
   - Show execution logs (if implemented)
   - Display DAG execution graph
   - Show step-by-step progress

#### Medium Priority

4. **Run Creation UI**
   - Form to create runs
   - Parameter input/validation
   - Pipeline version selection

5. **Tenant/Facility Management UI**
   - Create/manage tenants
   - Create/manage facilities
   - View tenant hierarchy

6. **Worker Management**
   - View active workers
   - Worker health monitoring
   - Worker metrics/statistics

#### Low Priority

7. **Authentication & Authorization**
   - User authentication
   - Role-based access control
   - API key management

8. **Advanced Filtering**
   - Date range filters
   - Multi-status filtering
   - Search by run ID/tenant ID

9. **Metrics & Monitoring**
   - Run success/failure rates
   - Average execution time
   - Worker utilization
   - Queue depth monitoring

10. **Actual Pipeline Execution**
    - Replace simulation with real DAG execution
    - Step-by-step execution
    - Intermediate state tracking
    - Retry logic

---

## Troubleshooting

### Common Issues

#### PostgreSQL Connection Errors

**Problem:** `psycopg.OperationalError: could not connect to server`

**Solutions:**
1. Verify PostgreSQL container is running: `docker ps | Select-String "nextlayer-postgres"`
2. Check connection string matches docker-compose.yml settings
3. Ensure port 5432 is not blocked by firewall

#### Migration Errors

**Problem:** `alembic.util.exc.CommandError: Target database is not up to date`

**Solutions:**
1. Check current migration: `alembic current`
2. View migration history: `alembic history`
3. Apply pending migrations: `alembic upgrade head`
4. If stuck, check database state manually in psql

#### CORS Errors in Dashboard

**Problem:** Browser console shows CORS errors when calling API

**Solutions:**
1. Verify `CORS_ORIGINS` includes dashboard URL (default: `http://localhost:3000`)
2. Check API is running on correct port (8000)
3. Ensure dashboard uses correct `NEXT_PUBLIC_CP_BASE` value

#### Worker Not Claiming Runs

**Problem:** Worker shows "No queued runs" but runs exist

**Solutions:**
1. Verify runs have status `QUEUED` (not RUNNING/SUCCEEDED/FAILED)
2. Check `TENANT_ID` filter matches run's tenant_id (if set)
3. Verify API is accessible: `curl http://localhost:8000/health`
4. Check worker logs for errors

#### Timezone Display Issues

**Problem:** Timestamps show incorrect times in dashboard

**Solutions:**
1. Verify database columns are `timestamptz` (not `timestamp`)
2. Check API returns ISO strings with timezone offset (`+00:00`)
3. Ensure browser timezone is set correctly
4. Verify migration `a1b2c3d4e5f6_pipeline_runs_timestamptz.py` was applied

---

## Contributing

### Code Style

- **Python**: Follow PEP 8, use type hints
- **TypeScript/React**: Use TypeScript strict mode, follow Next.js conventions
- **SQL**: Use Alembic migrations for schema changes

### Git Workflow

1. Create feature branch from `master`
2. Make changes with descriptive commits
3. Test locally using verification runbook
4. Submit pull request with description

### Testing

- Manual testing via verification runbook
- API testing via Swagger UI (`/docs`)
- Database verification via psql queries

---

## License

[Add license information here]

---

## Contact

[Add contact information here]

---

**Document Version:** 1.0  
**Last Updated:** February 2026  
**Maintained by:** NextLayer Team
#   A R I 
 
 #   A R I 
 
 