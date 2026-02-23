"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

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
  const router = useRouter();
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
    const url = `${CP_BASE}/api/runs/${runId}/logs?limit=200&order=asc`;
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

  const handleRetry = useCallback(async () => {
    if (!id) return;
    setActionLoading(true);
    setActionFeedback(null);
    try {
      const res = await fetch(`${CP_BASE}/api/runs/${id}/retry`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      const json = await res.json().catch(() => ({}));
      if (!res.ok) {
        setActionFeedback({ ok: false, message: json.reason ?? json.detail ?? `HTTP ${res.status}` });
        return;
      }
      const newRunId = json.run?.id;
      if (newRunId) {
        router.push(`/runs/${newRunId}`);
        return;
      }
      setActionFeedback({ ok: true, message: "Retry created" });
      fetchRun(id);
    } catch (err) {
      setActionFeedback({ ok: false, message: err instanceof Error ? err.message : "Request failed" });
    } finally {
      setActionLoading(false);
    }
  }, [id, router, fetchRun]);

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
            <button
              type="button"
              onClick={handleRetry}
              className="px-3 py-1.5 text-sm font-medium rounded bg-blue-200 text-blue-800 dark:bg-blue-900 dark:text-blue-200 hover:bg-blue-300 dark:hover:bg-blue-800"
            >
              Retry
            </button>
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
            <div className="p-2 space-y-1">
              {logs.map((entry) => (
                <div
                  key={entry.id}
                  className="flex gap-2 items-baseline break-words"
                >
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
              ))}
              <div ref={logsEndRef} />
            </div>
          )}
        </div>
      </section>
    </main>
  );
}
