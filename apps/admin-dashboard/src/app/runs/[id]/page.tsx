"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import Link from "next/link";
import { RetryRunButton } from "@/components/runs/RetryRunButton";

const CP_BASE =
  (typeof process !== "undefined" && process.env.NEXT_PUBLIC_CP_BASE) ||
  "http://localhost:8000";

type RunDetail = {
  id: string;
  tenant_id: string;
  pipeline_version_id: string;
  status: string;
  trigger_type?: string;
  parameters: Record<string, unknown> | null;
  claimed_by: string | null;
  claimed_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  heartbeat_at: string | null;
  error_message: string | null;
  created_at: string | null;
  updated_at: string | null;
  pipeline_id?: string;
  retry_of_run_id?: string | null;
  root_run_id?: string | null;
};

type DetailResponse = { found: boolean; run?: RunDetail; reason?: string };

function shortId(id: string, len = 8): string {
  return id.length > len ? `${id.slice(0, len)}…` : id;
}

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

function statusBadgeClass(status: string): string {
  const base = "inline-flex px-2 py-0.5 text-xs font-medium rounded";
  switch (status) {
    case "QUEUED":
      return `${base} bg-gray-200 text-gray-800 dark:bg-gray-700 dark:text-gray-200`;
    case "RUNNING":
      return `${base} bg-blue-200 text-blue-800 dark:bg-blue-900 dark:text-blue-200`;
    case "SUCCEEDED":
      return `${base} bg-green-200 text-green-800 dark:bg-green-900 dark:text-green-200`;
    case "FAILED":
      return `${base} bg-red-200 text-red-800 dark:bg-red-900 dark:text-red-200`;
    case "CANCELLED":
      return `${base} bg-amber-200 text-amber-800 dark:bg-amber-900 dark:text-amber-200`;
    default:
      return `${base} bg-gray-100 text-gray-700`;
  }
}

const TERMINAL_STATUSES = ["SUCCEEDED", "FAILED", "CANCELLED"];

type LogEntry = {
  id: string;
  ts: string;
  level: string;
  message: string;
  source?: string | null;
  meta?: Record<string, unknown> | null;
};

type LogsResponse = { found: boolean; run_id: string; logs: LogEntry[] };

function logLevelBadgeClass(level: string): string {
  const base = "inline-flex px-1.5 py-0.5 text-xs font-medium rounded shrink-0";
  switch (level.toUpperCase()) {
    case "ERROR":
      return `${base} bg-red-200 text-red-800 dark:bg-red-900 dark:text-red-200`;
    case "WARN":
      return `${base} bg-amber-200 text-amber-800 dark:bg-amber-900 dark:text-amber-200`;
    case "DEBUG":
      return `${base} bg-gray-200 text-gray-600 dark:bg-gray-700 dark:text-gray-300`;
    default:
      return `${base} bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-200`;
  }
}

export default function RunDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const [id, setId] = useState<string | null>(null);
  const [run, setRun] = useState<RunDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [paramsCollapsed, setParamsCollapsed] = useState(true);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [logsError, setLogsError] = useState<string | null>(null);
  const [actionLoading, setActionLoading] = useState(false);
  const [actionFeedback, setActionFeedback] = useState<{ ok: boolean; message: string } | null>(null);
  const [retryChildren, setRetryChildren] = useState<RunDetail[]>([]);
  const [retryChildrenError, setRetryChildrenError] = useState<string | null>(null);
  const [retryChildrenFetched, setRetryChildrenFetched] = useState(false);
  const logsEndRef = useRef<HTMLDivElement>(null);
  const logsScrollRef = useRef<HTMLDivElement>(null);
  const userScrolledUpRef = useRef(false);

  type InventoryDelta = {
    changed_skus_count?: number;
    unchanged_skus_count?: number;
    new_skus_count?: number;
    removed_skus_count?: number;
    removed_skus_sample?: string[];
    new_out_of_stock_skus?: string[];
    back_in_stock_skus?: string[];
    quantity_changed_skus_count?: number;
    top_deltas?: Array<{
      sku: string;
      previous_on_hand: number;
      current_on_hand: number;
      delta_on_hand: number;
    }>;
    total_on_hand_previous?: number;
    total_on_hand_current?: number;
    total_on_hand_delta?: number;
  };

  type InventorySummary = {
    facility_id: string;
    tenant_id?: string;
    provider: string;
    fixture_used?: string;
    as_of: string | null;
    items_total: number;
    out_of_stock: number;
    out_of_stock_skus_sample: string[];
    delta?: InventoryDelta | null;
  } | null;

  const [inventorySummary, setInventorySummary] = useState<InventorySummary>(null);
  const [inventorySummaryError, setInventorySummaryError] = useState<string | null>(null);

  const fetchRun = useCallback(async (runId: string) => {
    const url = `${CP_BASE}/api/runs/${runId}`;
    const res = await fetch(url);
    const json: DetailResponse = await res.json().catch(() => ({}));

    if (!res.ok) {
      if (res.status === 404) {
        setError("Run not found");
        setRun(null);
      } else {
        setError(`Failed to load run (${res.status} ${res.statusText || "error"})`);
        setRun(null);
      }
      setLoading(false);
      return;
    }

    if (json.found && json.run) {
      setRun(json.run);
      setError(null);
    } else {
      setError("Run not found");
      setRun(null);
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    let resolved = false;
    params.then((p) => {
      if (!resolved) setId(p.id);
    });
    return () => {
      resolved = true;
    };
  }, [params]);

  useEffect(() => {
    if (!id) return;
    fetchRun(id);
  }, [id, fetchRun]);

  // Poll when run is not terminal (QUEUED or RUNNING); clear on unmount
  useEffect(() => {
    if (!id || !run || TERMINAL_STATUSES.includes(run.status)) return;
    const interval = setInterval(() => fetchRun(id), 2000);
    return () => clearInterval(interval);
  }, [id, run?.status, fetchRun]);

  const fetchLogs = useCallback(async (runId: string) => {
    const url = `${CP_BASE}/api/runs/${runId}/logs?limit=400&order=asc`;
    try {
      const res = await fetch(url);
      if (!res.ok) {
        setLogsError(`Logs: ${res.status} ${res.statusText || "error"}`);
        return;
      }
      const json: LogsResponse = await res.json();
      if (json.found && Array.isArray(json.logs)) {
        setLogs(json.logs);
        setLogsError(null);
      }
    } catch (err) {
      setLogsError("Failed to load logs");
    }
  }, []);

  // Fetch logs on load and poll while run is not terminal
  useEffect(() => {
    if (!id) return;
    fetchLogs(id);
  }, [id, fetchLogs]);

  useEffect(() => {
    if (!id || !run) return;
    if (TERMINAL_STATUSES.includes(run.status)) {
      // One final fetch when becoming terminal, then stop
      fetchLogs(id);
      return;
    }
    const interval = setInterval(() => fetchLogs(id), 2000);
    return () => clearInterval(interval);
  }, [id, run?.status, fetchLogs]);

  // Fetch latest inventory summary artifact (if any); poll while run is active
  useEffect(() => {
    if (!id) return;
    const load = () => {
      const url = `${CP_BASE}/api/runs/${id}/artifacts?artifact_type=inventory_summary&order=desc&limit=1`;
      fetch(url)
        .then((res) => {
          if (!res.ok) {
            throw new Error(`HTTP ${res.status}`);
          }
          return res.json();
        })
        .then((data: { items?: { payload?: Record<string, unknown> }[] }) => {
          const artifact = Array.isArray(data.items) && data.items.length > 0 ? data.items[0] : null;
          if (artifact && artifact.payload && typeof artifact.payload === "object") {
            const p = artifact.payload;
            const rawDelta = p.delta;
            let delta: InventoryDelta | null | undefined;
            if (rawDelta && typeof rawDelta === "object") {
              const d = rawDelta as Record<string, unknown>;
              delta = {
                changed_skus_count: typeof d.changed_skus_count === "number" ? d.changed_skus_count : undefined,
                unchanged_skus_count: typeof d.unchanged_skus_count === "number" ? d.unchanged_skus_count : undefined,
                new_skus_count: typeof d.new_skus_count === "number" ? d.new_skus_count : undefined,
                removed_skus_count: typeof d.removed_skus_count === "number" ? d.removed_skus_count : undefined,
                removed_skus_sample: Array.isArray(d.removed_skus_sample)
                  ? (d.removed_skus_sample as string[])
                  : undefined,
                new_out_of_stock_skus: Array.isArray(d.new_out_of_stock_skus)
                  ? (d.new_out_of_stock_skus as string[])
                  : undefined,
                back_in_stock_skus: Array.isArray(d.back_in_stock_skus)
                  ? (d.back_in_stock_skus as string[])
                  : undefined,
                quantity_changed_skus_count:
                  typeof d.quantity_changed_skus_count === "number" ? d.quantity_changed_skus_count : undefined,
                top_deltas: Array.isArray(d.top_deltas) ? (d.top_deltas as InventoryDelta["top_deltas"]) : undefined,
                total_on_hand_previous:
                  typeof d.total_on_hand_previous === "number" ? d.total_on_hand_previous : undefined,
                total_on_hand_current:
                  typeof d.total_on_hand_current === "number" ? d.total_on_hand_current : undefined,
                total_on_hand_delta: typeof d.total_on_hand_delta === "number" ? d.total_on_hand_delta : undefined,
              };
            }
            setInventorySummary({
              facility_id: String(p.facility_id ?? ""),
              tenant_id: typeof p.tenant_id === "string" ? p.tenant_id : undefined,
              provider: String(p.provider ?? ""),
              fixture_used: typeof p.fixture_used === "string" ? p.fixture_used : undefined,
              as_of: typeof p.as_of === "string" ? p.as_of : null,
              items_total: Number(p.items_total ?? 0),
              out_of_stock: Number(p.out_of_stock ?? 0),
              out_of_stock_skus_sample: Array.isArray(p.out_of_stock_skus_sample)
                ? (p.out_of_stock_skus_sample as string[])
                : [],
              delta: delta ?? null,
            });
            setInventorySummaryError(null);
          } else {
            setInventorySummary(null);
          }
        })
        .catch(() => {
          setInventorySummary(null);
          setInventorySummaryError("Could not load inventory summary");
        });
    };
    load();
    if (!run || TERMINAL_STATUSES.includes(run.status)) return;
    const interval = setInterval(load, 2000);
    return () => clearInterval(interval);
  }, [id, run?.status]);

  // Fetch child retries (runs created from this run) for "Retries" section
  useEffect(() => {
    if (!id) return;
    setRetryChildrenFetched(false);
    const url = `${CP_BASE}/api/runs?retry_of_run_id=${encodeURIComponent(id)}&limit=50&offset=0`;
    fetch(url)
      .then((res) => res.json())
      .then((data: { items?: RunDetail[] }) => {
        setRetryChildren(Array.isArray(data.items) ? data.items : []);
        setRetryChildrenError(null);
        setRetryChildrenFetched(true);
      })
      .catch(() => {
        setRetryChildren([]);
        setRetryChildrenError("Could not load retries");
        setRetryChildrenFetched(true);
      });
  }, [id]);

  const handleCancel = useCallback(async () => {
    if (!id) return;
    setActionLoading(true);
    setActionFeedback(null);
    try {
      const res = await fetch(`${CP_BASE}/api/runs/${id}/cancel`, { method: "POST" });
      const json = await res.json().catch(() => ({}));
      if (!res.ok) {
        setActionFeedback({ ok: false, message: json.reason ?? json.detail ?? `HTTP ${res.status}` });
        return;
      }
      setActionFeedback({ ok: true, message: "Cancelled" });
      fetchRun(id);
      fetchLogs(id);
    } catch (err) {
      setActionFeedback({ ok: false, message: err instanceof Error ? err.message : "Request failed" });
    } finally {
      setActionLoading(false);
    }
  }, [id, fetchRun, fetchLogs]);

  // Auto-scroll to bottom when new logs arrive, only if user hasn't scrolled up
  useEffect(() => {
    if (!userScrolledUpRef.current && logs.length > 0) {
      logsEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [logs]);

  if (!id) {
    return (
      <main className="p-6 max-w-3xl mx-auto">
        <p className="text-gray-500">Loading…</p>
      </main>
    );
  }

  if (loading && !run) {
    return (
      <main className="p-6 max-w-3xl mx-auto">
        <div className="animate-pulse space-y-3">
          <div className="h-4 w-48 bg-gray-200 dark:bg-gray-700 rounded" />
          <div className="h-4 w-full bg-gray-200 dark:bg-gray-700 rounded" />
          <div className="h-4 w-3/4 bg-gray-200 dark:bg-gray-700 rounded" />
        </div>
        <p className="mt-4 text-gray-500 text-sm">Loading…</p>
      </main>
    );
  }

  if (error && !run) {
    return (
      <main className="p-6 max-w-3xl mx-auto">
        <p className="text-red-600 dark:text-red-400" role="alert">
          {error}
        </p>
        <Link
          href="/runs"
          className="mt-2 inline-block text-blue-600 dark:text-blue-400 hover:underline text-sm"
        >
          ← Back to runs
        </Link>
      </main>
    );
  }

  const r = run!;
  const paramsStr =
    r.parameters != null && Object.keys(r.parameters).length > 0
      ? JSON.stringify(r.parameters, null, 2)
      : "";
  const paramsLarge = paramsStr.length > 500;

  return (
    <main className="p-6 max-w-3xl mx-auto">
      <Link
        href="/runs"
        className="text-sm text-blue-600 dark:text-blue-400 hover:underline mb-4 inline-block"
      >
        ← Back to runs
      </Link>

      <h1 className="text-xl font-bold mb-4">
        Run {shortId(r.id)}
        <span className="ml-2 font-mono text-sm font-normal text-gray-500 dark:text-gray-400" title={r.id}>
          ({r.id})
        </span>
      </h1>

      {/* Run identity */}
      <section className="mb-6">
        <h2 className="text-sm font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-2">
          Identity
        </h2>
        <dl className="grid grid-cols-[minmax(10rem,auto)_1fr] gap-2 text-sm">
          <dt className="text-gray-500 dark:text-gray-400">ID</dt>
          <dd className="font-mono break-all" title={r.id}>
            {r.id}
          </dd>
          <dt className="text-gray-500 dark:text-gray-400">Short ID</dt>
          <dd className="font-mono">{shortId(r.id)}</dd>
          <dt className="text-gray-500 dark:text-gray-400">Tenant ID</dt>
          <dd className="font-mono break-all">{r.tenant_id}</dd>
          {r.pipeline_id != null && r.pipeline_id !== "" && (
            <>
              <dt className="text-gray-500 dark:text-gray-400">Pipeline ID</dt>
              <dd className="font-mono break-all">{r.pipeline_id}</dd>
            </>
          )}
          <dt className="text-gray-500 dark:text-gray-400">Pipeline version ID</dt>
          <dd className="font-mono break-all" title={r.pipeline_version_id}>
            {shortId(r.pipeline_version_id)} — {r.pipeline_version_id}
          </dd>
          {r.retry_of_run_id != null && r.retry_of_run_id !== "" && (
            <>
              <dt className="text-gray-500 dark:text-gray-400">Retry of</dt>
              <dd>
                <Link
                  href={`/runs/${r.retry_of_run_id}`}
                  className="font-mono text-blue-600 dark:text-blue-400 hover:underline"
                  title={r.retry_of_run_id}
                >
                  {shortId(r.retry_of_run_id)}
                </Link>
              </dd>
            </>
          )}
        </dl>
      </section>

      {/* Retries (child runs created from this run) */}
      {retryChildrenFetched && (
        <section className="mb-6">
          <h2 className="text-sm font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-2">
            Retries
          </h2>
          {retryChildrenError ? (
            <p className="text-sm text-amber-600 dark:text-amber-400">{retryChildrenError}</p>
          ) : retryChildren.length === 0 ? (
            <p className="text-sm text-gray-500">No retries yet.</p>
          ) : (
            <ul className="list-disc list-inside text-sm space-y-1">
              {retryChildren.map((child) => (
                <li key={child.id}>
                  <Link
                    href={`/runs/${child.id}`}
                    className="font-mono text-blue-600 dark:text-blue-400 hover:underline"
                    title={child.id}
                  >
                    {shortId(child.id)}
                  </Link>
                  {child.status != null && child.status !== "" && (
                    <span className="ml-2">
                      <span className={statusBadgeClass(child.status)}>{child.status}</span>
                    </span>
                  )}
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      {/* Status */}
      <section className="mb-6">
        <h2 className="text-sm font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-2">
          Status
        </h2>
        <dl className="grid grid-cols-[minmax(10rem,auto)_1fr] gap-2 text-sm">
          <dt className="text-gray-500 dark:text-gray-400">Status</dt>
          <dd>
            <span className={statusBadgeClass(r.status)}>{r.status}</span>
          </dd>
          <dt className="text-gray-500 dark:text-gray-400">Claimed by</dt>
          <dd>{r.claimed_by ?? "—"}</dd>
        </dl>
      </section>

      {/* Actions */}
      <section className="mb-6">
        <h2 className="text-sm font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-2">
          Actions
        </h2>
        <div className="flex items-center gap-2">
          {actionLoading ? (
            <span className="text-gray-500 text-sm">…</span>
          ) : (r.status === "QUEUED" || r.status === "RUNNING") ? (
            <button
              type="button"
              onClick={handleCancel}
              className="px-3 py-1.5 text-sm font-medium rounded bg-amber-200 text-amber-800 dark:bg-amber-900 dark:text-amber-200 hover:bg-amber-300 dark:hover:bg-amber-800"
            >
              Cancel
            </button>
          ) : (r.status === "FAILED" || r.status === "CANCELLED") ? (
            <RetryRunButton
              runId={id}
              defaultParameters={r.parameters ?? undefined}
              className="px-3 py-1.5 text-sm font-medium rounded bg-blue-200 text-blue-800 dark:bg-blue-900 dark:text-blue-200 hover:bg-blue-300 dark:hover:bg-blue-800"
            />
          ) : (
            <span className="text-gray-500 text-sm">No actions for {r.status}</span>
          )}
          {actionFeedback && (
            <span
              className={
                actionFeedback.ok
                  ? "text-green-600 dark:text-green-400 text-sm"
                  : "text-red-600 dark:text-red-400 text-sm"
              }
            >
              {actionFeedback.message}
            </span>
          )}
        </div>
      </section>

      {/* Timestamps */}
      <section className="mb-6">
        <h2 className="text-sm font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-2">
          Timestamps
        </h2>
        <dl className="grid grid-cols-[minmax(10rem,auto)_1fr] gap-2 text-sm">
          <dt className="text-gray-500 dark:text-gray-400">Created at</dt>
          <dd>
            {formatDate(r.created_at)}
            {r.created_at && (
              <span className="ml-2 text-xs text-gray-400 font-mono" title="ISO">
                {r.created_at}
              </span>
            )}
          </dd>
          <dt className="text-gray-500 dark:text-gray-400">Claimed at</dt>
          <dd>{formatDate(r.claimed_at)}</dd>
          <dt className="text-gray-500 dark:text-gray-400">Started at</dt>
          <dd>{formatDate(r.started_at)}</dd>
          <dt className="text-gray-500 dark:text-gray-400">Finished at</dt>
          <dd>{formatDate(r.finished_at)}</dd>
          {r.heartbeat_at != null && (
            <>
              <dt className="text-gray-500 dark:text-gray-400">Heartbeat at</dt>
              <dd>{formatDate(r.heartbeat_at)}</dd>
            </>
          )}
        </dl>
      </section>

      {/* Error callout */}
      {(r.status === "FAILED" || (r.error_message != null && r.error_message !== "")) && (
        <section className="mb-6">
          <div
            className="p-3 rounded border border-red-300 dark:border-red-800 bg-red-50 dark:bg-red-900/20 text-red-800 dark:text-red-200 text-sm"
            role="alert"
          >
            <strong>Error</strong>: {r.error_message ?? "—"}
          </div>
        </section>
      )}

      {/* Parameters */}
      <section className="mb-6">
        <h2 className="text-sm font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-2">
          Parameters
        </h2>
        {paramsStr ? (
          <div className="rounded border border-gray-200 dark:border-gray-700 overflow-hidden">
            {paramsLarge && (
              <button
                type="button"
                onClick={() => setParamsCollapsed((c) => !c)}
                className="w-full px-3 py-2 text-left text-xs font-medium text-gray-600 dark:text-gray-400 bg-gray-50 dark:bg-gray-800/50 hover:bg-gray-100 dark:hover:bg-gray-800"
              >
                {paramsCollapsed ? "Expand" : "Collapse"} JSON
              </button>
            )}
            <pre className="p-3 bg-gray-100 dark:bg-gray-800 text-xs overflow-x-auto overflow-y-auto max-h-96">
              {paramsLarge && paramsCollapsed
                ? `${paramsStr.slice(0, 400)}…`
                : paramsStr}
            </pre>
          </div>
        ) : (
          <p className="text-sm text-gray-500">—</p>
        )}
      </section>

      {/* Inventory Summary — after parameters so operators see inputs, outputs, then trace */}
      <section className="mb-6">
        <h2 className="text-sm font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-2">
          Inventory Summary
        </h2>
        {inventorySummaryError && (
          <p className="text-amber-600 dark:text-amber-400 text-sm mb-2">{inventorySummaryError}</p>
        )}
        {!inventorySummary && !inventorySummaryError ? (
          <p className="text-sm text-gray-500">No inventory summary for this run yet.</p>
        ) : inventorySummary ? (
          <div className="rounded border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900/40 p-3 text-sm space-y-3">
            <div className="space-y-1">
              <div>
                <span className="text-gray-500 dark:text-gray-400">Facility:</span>{" "}
                <span className="font-mono break-all">{inventorySummary.facility_id || "—"}</span>
              </div>
              {inventorySummary.tenant_id != null && inventorySummary.tenant_id !== "" && (
                <div>
                  <span className="text-gray-500 dark:text-gray-400">Tenant:</span>{" "}
                  <span className="font-mono break-all">{inventorySummary.tenant_id}</span>
                </div>
              )}
              <div>
                <span className="text-gray-500 dark:text-gray-400">Provider:</span>{" "}
                <span className="font-mono">{inventorySummary.provider || "—"}</span>
              </div>
              {inventorySummary.fixture_used != null && inventorySummary.fixture_used !== "" && (
                <div>
                  <span className="text-gray-500 dark:text-gray-400">Fixture used:</span>{" "}
                  <span className="font-mono">{inventorySummary.fixture_used}</span>
                </div>
              )}
              <div>
                <span className="text-gray-500 dark:text-gray-400">As of:</span>{" "}
                <span>{inventorySummary.as_of ? formatDate(inventorySummary.as_of) : "—"}</span>
              </div>
              <div>
                <span className="text-gray-500 dark:text-gray-400">Items total:</span>{" "}
                <span className="font-mono">{inventorySummary.items_total}</span>
              </div>
              <div>
                <span className="text-gray-500 dark:text-gray-400">Out of stock:</span>{" "}
                <span className="font-mono">{inventorySummary.out_of_stock}</span>
              </div>
              <div>
                <span className="text-gray-500 dark:text-gray-400">Sample OOS SKUs:</span>{" "}
                {inventorySummary.out_of_stock_skus_sample.length === 0 ? (
                  <span className="font-mono text-gray-500">—</span>
                ) : (
                  <span className="font-mono">
                    {inventorySummary.out_of_stock_skus_sample.join(", ")}
                  </span>
                )}
              </div>
            </div>

            {inventorySummary.delta != null &&
              (typeof inventorySummary.delta.changed_skus_count === "number" ||
                typeof inventorySummary.delta.new_skus_count === "number" ||
                typeof inventorySummary.delta.removed_skus_count === "number") && (
                <div className="border-t border-gray-200 dark:border-gray-700 pt-3 space-y-2">
                  <p className="text-xs font-semibold text-gray-600 dark:text-gray-300 uppercase tracking-wide">
                    Change vs prior canonical state
                  </p>
                  <dl className="grid grid-cols-[minmax(10rem,auto)_1fr] gap-x-2 gap-y-1">
                    <dt className="text-gray-500 dark:text-gray-400">Changed SKUs</dt>
                    <dd className="font-mono">
                      {inventorySummary.delta.changed_skus_count ?? "—"}
                    </dd>
                    <dt className="text-gray-500 dark:text-gray-400">Unchanged SKUs</dt>
                    <dd className="font-mono">
                      {inventorySummary.delta.unchanged_skus_count ?? "—"}
                    </dd>
                    <dt className="text-gray-500 dark:text-gray-400">New SKUs</dt>
                    <dd className="font-mono">{inventorySummary.delta.new_skus_count ?? "—"}</dd>
                    <dt className="text-gray-500 dark:text-gray-400">Removed SKUs</dt>
                    <dd className="font-mono">
                      {inventorySummary.delta.removed_skus_count ?? "—"}
                      {Array.isArray(inventorySummary.delta.removed_skus_sample) &&
                        inventorySummary.delta.removed_skus_sample.length > 0 && (
                          <span className="text-gray-500 dark:text-gray-400 ml-1">
                            ({inventorySummary.delta.removed_skus_sample.join(", ")})
                          </span>
                        )}
                    </dd>
                    <dt className="text-gray-500 dark:text-gray-400">On-hand qty changed</dt>
                    <dd className="font-mono">
                      {inventorySummary.delta.quantity_changed_skus_count ?? "—"}
                    </dd>
                    {(typeof inventorySummary.delta.total_on_hand_previous === "number" ||
                      typeof inventorySummary.delta.total_on_hand_current === "number") && (
                      <>
                        <dt className="text-gray-500 dark:text-gray-400">Total on-hand (prev → curr)</dt>
                        <dd className="font-mono">
                          {typeof inventorySummary.delta.total_on_hand_previous === "number"
                            ? inventorySummary.delta.total_on_hand_previous
                            : "—"}
                          {" → "}
                          {typeof inventorySummary.delta.total_on_hand_current === "number"
                            ? inventorySummary.delta.total_on_hand_current
                            : "—"}
                          {typeof inventorySummary.delta.total_on_hand_delta === "number" && (
                            <span
                              className={
                                inventorySummary.delta.total_on_hand_delta === 0
                                  ? "text-gray-600 dark:text-gray-400"
                                  : inventorySummary.delta.total_on_hand_delta > 0
                                    ? "text-green-700 dark:text-green-400"
                                    : "text-amber-800 dark:text-amber-300"
                              }
                            >
                              {" "}
                              (Δ {inventorySummary.delta.total_on_hand_delta > 0 ? "+" : ""}
                              {inventorySummary.delta.total_on_hand_delta})
                            </span>
                          )}
                        </dd>
                      </>
                    )}
                  </dl>

                  <div>
                    <span className="text-gray-500 dark:text-gray-400">Newly out of stock (sample):</span>{" "}
                    {Array.isArray(inventorySummary.delta.new_out_of_stock_skus) &&
                    inventorySummary.delta.new_out_of_stock_skus.length > 0 ? (
                      <span className="font-mono">
                        {inventorySummary.delta.new_out_of_stock_skus.join(", ")}
                      </span>
                    ) : (
                      <span className="text-gray-500 text-xs">No newly out-of-stock SKUs</span>
                    )}
                  </div>
                  <div>
                    <span className="text-gray-500 dark:text-gray-400">Back in stock (sample):</span>{" "}
                    {Array.isArray(inventorySummary.delta.back_in_stock_skus) &&
                    inventorySummary.delta.back_in_stock_skus.length > 0 ? (
                      <span className="font-mono">
                        {inventorySummary.delta.back_in_stock_skus.join(", ")}
                      </span>
                    ) : (
                      <span className="text-gray-500 text-xs">No back-in-stock SKUs</span>
                    )}
                  </div>

                  {Array.isArray(inventorySummary.delta.top_deltas) &&
                    inventorySummary.delta.top_deltas.length > 0 && (
                      <div>
                        <p className="text-gray-500 dark:text-gray-400 mb-1">Top on-hand deltas</p>
                        <ul className="font-mono text-xs space-y-0.5 list-disc list-inside pl-1">
                          {inventorySummary.delta.top_deltas.map((row) => (
                            <li key={row.sku}>
                              <span className="text-gray-700 dark:text-gray-200">{row.sku}</span>
                              {" — "}
                              {row.previous_on_hand} → {row.current_on_hand}
                              {" "}
                              <span
                                className={
                                  row.delta_on_hand === 0
                                    ? "text-gray-500"
                                    : row.delta_on_hand > 0
                                      ? "text-green-700 dark:text-green-400"
                                      : "text-amber-800 dark:text-amber-300"
                                }
                              >
                                ({row.delta_on_hand > 0 ? "+" : ""}
                                {row.delta_on_hand})
                              </span>
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                </div>
              )}
          </div>
        ) : null}
      </section>

      {/* Logs */}
      <section className="mb-6">
        <h2 className="text-sm font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-2">
          Logs
        </h2>
        {logsError && (
          <p className="text-amber-600 dark:text-amber-400 text-sm mb-2" role="status">
            {logsError}
          </p>
        )}
        <div
          ref={logsScrollRef}
          className="rounded border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900/50 max-h-96 overflow-y-auto overflow-x-auto font-mono text-xs"
          onScroll={() => {
            const el = logsScrollRef.current;
            if (!el) return;
            const { scrollTop, clientHeight, scrollHeight } = el;
            const atBottom = scrollHeight - scrollTop - clientHeight < 40;
            userScrolledUpRef.current = !atBottom;
          }}
        >
          {logs.length === 0 && !logsError ? (
            <p className="p-3 text-gray-500">No logs yet.</p>
          ) : (
            <div className="p-2 space-y-2">
              {logs.map((entry) => (
                <div key={entry.id} className="min-w-0">
                  <div className="flex gap-2 items-baseline break-words">
                    <span className="text-gray-500 dark:text-gray-400 shrink-0" title={entry.ts}>
                      {formatDate(entry.ts)}
                    </span>
                    <span className={logLevelBadgeClass(entry.level)}>{entry.level}</span>
                    {entry.source && (
                      <span className="text-gray-500 dark:text-gray-400 shrink-0">
                        [{entry.source}]
                      </span>
                    )}
                    <span className="min-w-0">{entry.message}</span>
                  </div>
                  {entry.meta != null &&
                    typeof entry.meta === "object" &&
                    Object.keys(entry.meta).length > 0 && (
                      <div className="pl-0 sm:pl-36 mt-0.5 text-[10px] leading-snug text-gray-500 dark:text-gray-500 opacity-90 break-all font-mono">
                        {JSON.stringify(entry.meta)}
                      </div>
                    )}
                </div>
              ))}
              <div ref={logsEndRef} />
            </div>
          )}
        </div>
      </section>
    </main>
  );
}
