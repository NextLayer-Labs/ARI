"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import { TriggerRunButton } from "@/components/TriggerRunButton";

const CP_BASE =
  (typeof process !== "undefined" && process.env.NEXT_PUBLIC_CP_BASE) ||
  "http://localhost:8000";

type PipelineVersionItem = {
  id: string;
  tenant_id: string;
  pipeline_id: string;
  version: string;
  status: string;
  created_at: string | null;
  pipeline_name?: string | null;
};

type PipelineVersionsResponse = {
  items: PipelineVersionItem[];
  limit: number;
  offset: number;
  total: number;
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

const STATUS_OPTIONS = [
  { value: "", label: "All" },
  { value: "DRAFT", label: "DRAFT" },
  { value: "APPROVED", label: "APPROVED" },
  { value: "DEPRECATED", label: "DEPRECATED" },
];

const DEFAULT_LIMIT = 20;

export default function PipelineVersionsPage() {
  const [data, setData] = useState<PipelineVersionsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState("");
  const [tenantIdFilter, setTenantIdFilter] = useState("");
  const [pipelineIdFilter, setPipelineIdFilter] = useState("");
  const [offset, setOffset] = useState(0);
  const [actionFeedback, setActionFeedback] = useState<{
    id: string;
    ok: boolean;
    message: string;
  } | null>(null);
  const [loadingId, setLoadingId] = useState<string | null>(null);

  const fetchVersions = useCallback(() => {
    const params = new URLSearchParams({
      limit: String(DEFAULT_LIMIT),
      offset: String(offset),
    });
    if (statusFilter) params.set("status", statusFilter);
    if (tenantIdFilter.trim()) params.set("tenant_id", tenantIdFilter.trim());
    if (pipelineIdFilter.trim()) params.set("pipeline_id", pipelineIdFilter.trim());
    const url = `${CP_BASE}/api/pipeline-versions?${params.toString()}`;
    setLoading(true);
    fetch(url)
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((json: PipelineVersionsResponse) => {
        setData(json);
        setError(null);
      })
      .catch((err) => setError(err.message ?? "Failed to fetch pipeline versions"))
      .finally(() => setLoading(false));
  }, [offset, statusFilter, tenantIdFilter, pipelineIdFilter]);

  useEffect(() => {
    fetchVersions();
  }, [fetchVersions]);

  const handleApplyFilters = (e: React.FormEvent) => {
    e.preventDefault();
    setOffset(0);
  };

  const setStatus = async (id: string, status: "APPROVED" | "DEPRECATED") => {
    setLoadingId(id);
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
          id,
          ok: false,
          message: json.detail ?? `HTTP ${res.status}`,
        });
        return;
      }
      setActionFeedback({
        id,
        ok: true,
        message: status === "APPROVED" ? "Approved" : "Deprecated",
      });
      fetchVersions();
    } catch (err) {
      setActionFeedback({
        id,
        ok: false,
        message: err instanceof Error ? err.message : "Request failed",
      });
    } finally {
      setLoadingId(null);
    }
  };

  return (
    <main className="p-6 max-w-7xl mx-auto">
      <h1 className="text-2xl font-bold mb-4">Pipeline Versions</h1>

      {error && (
        <div
          className="mb-4 p-3 bg-red-100 dark:bg-red-900/30 text-red-800 dark:text-red-200 rounded text-sm"
          role="alert"
        >
          {error}
        </div>
      )}

      <form onSubmit={handleApplyFilters} className="mb-4 flex flex-wrap items-end gap-4">
        <label className="text-sm font-medium flex flex-col gap-1">
          Status
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="border border-gray-300 dark:border-gray-600 rounded px-3 py-1.5 bg-white dark:bg-gray-800 text-sm"
          >
            {STATUS_OPTIONS.map((opt) => (
              <option key={opt.value || "all"} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm font-medium flex flex-col gap-1">
          Tenant ID
          <input
            type="text"
            value={tenantIdFilter}
            onChange={(e) => setTenantIdFilter(e.target.value)}
            placeholder="Optional"
            className="border border-gray-300 dark:border-gray-600 rounded px-3 py-1.5 bg-white dark:bg-gray-800 text-sm font-mono w-48"
          />
        </label>
        <label className="text-sm font-medium flex flex-col gap-1">
          Pipeline ID
          <input
            type="text"
            value={pipelineIdFilter}
            onChange={(e) => setPipelineIdFilter(e.target.value)}
            placeholder="Optional"
            className="border border-gray-300 dark:border-gray-600 rounded px-3 py-1.5 bg-white dark:bg-gray-800 text-sm font-mono w-48"
          />
        </label>
        <button
          type="submit"
          className="px-3 py-1.5 rounded bg-gray-200 dark:bg-gray-700 text-sm font-medium hover:bg-gray-300 dark:hover:bg-gray-600"
        >
          Apply filters
        </button>
      </form>

      {loading && !data ? (
        <p className="text-gray-500">Loading…</p>
      ) : (
        <div className="overflow-x-auto rounded border border-gray-200 dark:border-gray-700">
          <table className="w-full text-sm text-left">
            <thead className="bg-gray-50 dark:bg-gray-800/50">
              <tr>
                <th className="px-4 py-2 font-medium">Version ID</th>
                <th className="px-4 py-2 font-medium">Status</th>
                <th className="px-4 py-2 font-medium">Version</th>
                <th className="px-4 py-2 font-medium">Pipeline</th>
                <th className="px-4 py-2 font-medium">Tenant ID</th>
                <th className="px-4 py-2 font-medium">Created</th>
                <th className="px-4 py-2 font-medium">Actions</th>
              </tr>
            </thead>
            <tbody>
              {data?.items?.length ? (
                data.items.map((pv) => (
                  <tr
                    key={pv.id}
                    className="border-t border-gray-200 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-800/30"
                  >
                    <td className="px-4 py-2 font-mono">
                      <Link
                        href={`/pipeline-versions/${pv.id}`}
                        className="text-blue-600 dark:text-blue-400 hover:underline"
                        title={pv.id}
                      >
                        {shortId(pv.id)}
                      </Link>
                    </td>
                    <td className="px-4 py-2">
                      <span className={statusBadgeClass(pv.status)}>
                        {pv.status}
                      </span>
                    </td>
                    <td className="px-4 py-2">{pv.version}</td>
                    <td className="px-4 py-2 font-mono" title={pv.pipeline_id}>
                      {pv.pipeline_name ?? shortId(pv.pipeline_id)}
                    </td>
                    <td className="px-4 py-2 font-mono" title={pv.tenant_id}>
                      {shortId(pv.tenant_id)}
                    </td>
                    <td className="px-4 py-2">
                      {formatDate(pv.created_at)}
                    </td>
                    <td className="px-4 py-2">
                      {loadingId === pv.id ? (
                        <span className="text-gray-500 text-xs">…</span>
                      ) : pv.status === "DRAFT" ? (
                        <button
                          type="button"
                          onClick={() => setStatus(pv.id, "APPROVED")}
                          className="px-2 py-1 text-xs font-medium rounded bg-green-200 text-green-800 dark:bg-green-900 dark:text-green-200 hover:bg-green-300 dark:hover:bg-green-800"
                        >
                          Approve
                        </button>
                      ) : pv.status === "APPROVED" ? (
                        <span className="flex items-center gap-2 flex-wrap">
                          <TriggerRunButton
                            tenantId={pv.tenant_id}
                            pipelineVersionId={pv.id}
                            label="Run"
                          />
                          <button
                            type="button"
                            onClick={() => setStatus(pv.id, "DEPRECATED")}
                            className="px-2 py-1 text-xs font-medium rounded bg-amber-200 text-amber-800 dark:bg-amber-900 dark:text-amber-200 hover:bg-amber-300 dark:hover:bg-amber-800"
                          >
                            Deprecate
                          </button>
                        </span>
                      ) : (
                        "—"
                      )}
                      {actionFeedback?.id === pv.id && (
                        <span
                          className={
                            actionFeedback.ok
                              ? "ml-2 text-green-600 dark:text-green-400 text-xs"
                              : "ml-2 text-red-600 dark:text-red-400 text-xs"
                          }
                        >
                          {actionFeedback.message}
                        </span>
                      )}
                    </td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={7} className="px-4 py-6 text-gray-500 text-center">
                    No pipeline versions found.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {data && (
        <div className="mt-2 flex items-center gap-4">
          <p className="text-xs text-gray-500">
            Total: {data.total} — showing {data.offset + 1}–{Math.min(data.offset + data.items.length, data.total)} (limit {data.limit}, offset {data.offset})
          </p>
          <div className="flex gap-2">
            <button
              type="button"
              disabled={offset === 0}
              onClick={() => setOffset((o) => Math.max(0, o - DEFAULT_LIMIT))}
              className="px-2 py-1 text-sm rounded border border-gray-300 dark:border-gray-600 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              Prev
            </button>
            <button
              type="button"
              disabled={data.offset + data.items.length >= data.total}
              onClick={() => setOffset((o) => o + DEFAULT_LIMIT)}
              className="px-2 py-1 text-sm rounded border border-gray-300 dark:border-gray-600 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              Next
            </button>
          </div>
        </div>
      )}
    </main>
  );
}
