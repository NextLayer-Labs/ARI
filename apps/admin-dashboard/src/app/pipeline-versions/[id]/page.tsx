"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";

const CP_BASE =
  (typeof process !== "undefined" && process.env.NEXT_PUBLIC_CP_BASE) ||
  "http://localhost:8000";

type PipelineVersionDetail = {
  id: string;
  tenant_id: string;
  pipeline_id: string;
  version: string;
  status: string;
  dag_spec: Record<string, unknown>;
  created_at: string | null;
  pipeline_name?: string | null;
};

type DetailResponse = {
  found: boolean;
  pipeline_version?: PipelineVersionDetail;
  reason?: string;
};

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
    case "DRAFT":
      return `${base} bg-gray-200 text-gray-800 dark:bg-gray-700 dark:text-gray-200`;
    case "APPROVED":
      return `${base} bg-green-200 text-green-800 dark:bg-green-900 dark:text-green-200`;
    case "DEPRECATED":
      return `${base} bg-amber-200 text-amber-800 dark:bg-amber-900 dark:text-amber-200`;
    default:
      return `${base} bg-gray-100 text-gray-700`;
  }
}

export default function PipelineVersionDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const [id, setId] = useState<string | null>(null);
  const [pv, setPv] = useState<PipelineVersionDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [dagCollapsed, setDagCollapsed] = useState(true);
  const [actionFeedback, setActionFeedback] = useState<{
    ok: boolean;
    message: string;
  } | null>(null);
  const [actionLoading, setActionLoading] = useState(false);

  const fetchVersion = useCallback(async (versionId: string) => {
    const url = `${CP_BASE}/api/pipeline-versions/${versionId}`;
    const res = await fetch(url);
    const json: DetailResponse = await res.json().catch(() => ({}));

    if (!res.ok) {
      if (res.status === 404) {
        setError("Pipeline version not found");
        setPv(null);
      } else {
        setError(`Failed to load (${res.status} ${res.statusText || "error"})`);
        setPv(null);
      }
      setLoading(false);
      return;
    }

    if (json.found && json.pipeline_version) {
      setPv(json.pipeline_version);
      setError(null);
    } else {
      setError("Pipeline version not found");
      setPv(null);
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
    fetchVersion(id);
  }, [id, fetchVersion]);

  const setStatus = async (status: "APPROVED" | "DEPRECATED") => {
    if (!id) return;
    setActionLoading(true);
    setActionFeedback(null);
    try {
      const res = await fetch(
        `${CP_BASE}/api/pipeline-versions/${id}/status`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ status }),
        }
      );
      const json = await res.json().catch(() => ({}));
      if (!res.ok) {
        setActionFeedback({
          ok: false,
          message: json.detail ?? `HTTP ${res.status}`,
        });
        return;
      }
      setActionFeedback({
        ok: true,
        message: status === "APPROVED" ? "Approved" : "Deprecated",
      });
      fetchVersion(id);
    } catch (err) {
      setActionFeedback({
        ok: false,
        message: err instanceof Error ? err.message : "Request failed",
      });
    } finally {
      setActionLoading(false);
    }
  };

  if (!id) {
    return (
      <main className="p-6 max-w-3xl mx-auto">
        <p className="text-gray-500">Loading…</p>
      </main>
    );
  }

  if (loading && !pv) {
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

  if (error && !pv) {
    return (
      <main className="p-6 max-w-3xl mx-auto">
        <p className="text-red-600 dark:text-red-400" role="alert">
          {error}
        </p>
        <Link
          href="/pipeline-versions"
          className="mt-2 inline-block text-blue-600 dark:text-blue-400 hover:underline text-sm"
        >
          ← Back to pipeline versions
        </Link>
      </main>
    );
  }

  const v = pv!;
  const dagStr =
    v.dag_spec != null && Object.keys(v.dag_spec).length > 0
      ? JSON.stringify(v.dag_spec, null, 2)
      : "";
  const dagLarge = dagStr.length > 500;

  return (
    <main className="p-6 max-w-3xl mx-auto">
      <Link
        href="/pipeline-versions"
        className="text-sm text-blue-600 dark:text-blue-400 hover:underline mb-4 inline-block"
      >
        ← Back to pipeline versions
      </Link>

      <h1 className="text-xl font-bold mb-4">
        Version {shortId(v.id)}
        <span className="ml-2 font-mono text-sm font-normal text-gray-500 dark:text-gray-400" title={v.id}>
          ({v.id})
        </span>
      </h1>

      {/* Identity */}
      <section className="mb-6">
        <h2 className="text-sm font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-2">
          Identity
        </h2>
        <dl className="grid grid-cols-[minmax(10rem,auto)_1fr] gap-2 text-sm">
          <dt className="text-gray-500 dark:text-gray-400">ID</dt>
          <dd className="font-mono break-all" title={v.id}>
            {v.id}
          </dd>
          <dt className="text-gray-500 dark:text-gray-400">Short ID</dt>
          <dd className="font-mono">{shortId(v.id)}</dd>
          <dt className="text-gray-500 dark:text-gray-400">Status</dt>
          <dd>
            <span className={statusBadgeClass(v.status)}>{v.status}</span>
          </dd>
          <dt className="text-gray-500 dark:text-gray-400">Version</dt>
          <dd className="font-mono">{v.version}</dd>
          <dt className="text-gray-500 dark:text-gray-400">Tenant ID</dt>
          <dd className="font-mono break-all">{v.tenant_id}</dd>
          <dt className="text-gray-500 dark:text-gray-400">Pipeline ID</dt>
          <dd className="font-mono break-all" title={v.pipeline_id}>
            {v.pipeline_id}
          </dd>
          {v.pipeline_name != null && v.pipeline_name !== "" && (
            <>
              <dt className="text-gray-500 dark:text-gray-400">Pipeline name</dt>
              <dd>{v.pipeline_name}</dd>
            </>
          )}
        </dl>
      </section>

      {/* Timestamps */}
      <section className="mb-6">
        <h2 className="text-sm font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-2">
          Timestamps
        </h2>
        <dl className="grid grid-cols-[minmax(10rem,auto)_1fr] gap-2 text-sm">
          <dt className="text-gray-500 dark:text-gray-400">Created at</dt>
          <dd>
            {formatDate(v.created_at)}
            {v.created_at && (
              <span className="ml-2 text-xs text-gray-400 font-mono" title="ISO">
                {v.created_at}
              </span>
            )}
          </dd>
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
          ) : v.status === "DRAFT" ? (
            <button
              type="button"
              onClick={() => setStatus("APPROVED")}
              className="px-3 py-1.5 text-sm font-medium rounded bg-green-200 text-green-800 dark:bg-green-900 dark:text-green-200 hover:bg-green-300 dark:hover:bg-green-800"
            >
              Approve
            </button>
          ) : v.status === "APPROVED" ? (
            <button
              type="button"
              onClick={() => setStatus("DEPRECATED")}
              className="px-3 py-1.5 text-sm font-medium rounded bg-amber-200 text-amber-800 dark:bg-amber-900 dark:text-amber-200 hover:bg-amber-300 dark:hover:bg-amber-800"
            >
              Deprecate
            </button>
          ) : (
            <span className="text-gray-500 text-sm">No actions for {v.status}</span>
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

      {/* DAG spec */}
      <section className="mb-6">
        <h2 className="text-sm font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-2">
          DAG spec
        </h2>
        {dagStr ? (
          <div className="rounded border border-gray-200 dark:border-gray-700 overflow-hidden">
            {dagLarge && (
              <button
                type="button"
                onClick={() => setDagCollapsed((c) => !c)}
                className="w-full px-3 py-2 text-left text-xs font-medium text-gray-600 dark:text-gray-400 bg-gray-50 dark:bg-gray-800/50 hover:bg-gray-100 dark:hover:bg-gray-800"
              >
                {dagCollapsed ? "Expand" : "Collapse"} JSON
              </button>
            )}
            <pre className="p-3 bg-gray-100 dark:bg-gray-800 text-xs overflow-x-auto overflow-y-auto max-h-96">
              {dagLarge && dagCollapsed
                ? `${dagStr.slice(0, 400)}…`
                : dagStr}
            </pre>
          </div>
        ) : (
          <p className="text-sm text-gray-500">—</p>
        )}
      </section>
    </main>
  );
}
