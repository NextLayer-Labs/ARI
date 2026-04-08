"use client";

import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";

const CP_BASE =
  (typeof process !== "undefined" && process.env.NEXT_PUBLIC_CP_BASE) ||
  "http://localhost:8000";

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

type ReturnsSummary = {
  facility_id: string;
  tenant_id: string;
  returns_count: number;
  total_units: number;
  pending_count: number;
  received_count: number;
  processed_count: number;
  needs_attention_count: number;
  oldest_open_age_days: number | null;
};

type ReturnItem = {
  return_id: string;
  order_id: string | null;
  sku: string;
  quantity: number;
  status: string;
  reason_code: string | null;
  received_at: string | null;
  processed_at: string | null;
  source_run_id: string | null;
  source_provider: string | null;
};

type ReturnsHistoryRow = {
  run_id: string;
  status: string;
  created_at: string | null;
  finished_at: string | null;
  fixture_used: string | null;
  returns_count: number | null;
  total_units: number | null;
  pending_count: number | null;
  received_count: number | null;
  processed_count: number | null;
  needs_attention_count: number | null;
  artifact_present: boolean;
};

type SnapshotPipelineVersion = {
  id: string;
  pipeline_id: string;
  version: string;
  created_at: string | null;
  pipeline_name: string | null;
};

function Inner({ params }: { params: Promise<{ facilityId: string }> }) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const tenantId = searchParams.get("tenant_id")?.trim() || "";
  const [facilityId, setFacilityId] = useState<string | null>(null);
  const [summary, setSummary] = useState<ReturnsSummary | null>(null);
  const [items, setItems] = useState<ReturnItem[]>([]);
  const [history, setHistory] = useState<ReturnsHistoryRow[]>([]);
  const [latestPayload, setLatestPayload] = useState<Record<string, unknown> | null>(null);
  const [snapshotVersions, setSnapshotVersions] = useState<SnapshotPipelineVersion[]>([]);
  const [selectedPvId, setSelectedPvId] = useState("");
  const [fixtureOverride, setFixtureOverride] = useState("");
  const [triggerSubmitting, setTriggerSubmitting] = useState(false);
  const [triggerError, setTriggerError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    params.then((p) => {
      if (!cancelled) setFacilityId(decodeURIComponent(p.facilityId));
    });
    return () => {
      cancelled = true;
    };
  }, [params]);

  useEffect(() => {
    if (!facilityId || !tenantId) return;
    fetch(`${CP_BASE}/api/returns/facility-summary?tenant_id=${encodeURIComponent(tenantId)}&facility_id=${encodeURIComponent(facilityId)}`)
      .then((r) => r.json())
      .then((j) => setSummary(j as ReturnsSummary))
      .catch(() => setSummary(null));
    fetch(`${CP_BASE}/api/returns/items?tenant_id=${encodeURIComponent(tenantId)}&facility_id=${encodeURIComponent(facilityId)}&limit=200`)
      .then((r) => r.json())
      .then((j: { items?: ReturnItem[] }) => setItems(Array.isArray(j.items) ? j.items : []))
      .catch(() => setItems([]));
    fetch(`${CP_BASE}/api/returns/facility-history?tenant_id=${encodeURIComponent(tenantId)}&facility_id=${encodeURIComponent(facilityId)}&limit=25`)
      .then((r) => r.json())
      .then((j: { items?: ReturnsHistoryRow[] }) => setHistory(Array.isArray(j.items) ? j.items : []))
      .catch(() => setHistory([]));
  }, [facilityId, tenantId]);

  useEffect(() => {
    if (history.length === 0) {
      setLatestPayload(null);
      return;
    }
    const latestRun = history[0].run_id;
    fetch(`${CP_BASE}/api/runs/${encodeURIComponent(latestRun)}/artifacts?artifact_type=returns_summary&order=desc&limit=1`)
      .then((r) => r.json())
      .then((j: { items?: Array<{ payload?: Record<string, unknown> }> }) => {
        const payload = j.items?.[0]?.payload;
        setLatestPayload(payload && typeof payload === "object" ? payload : null);
      })
      .catch(() => setLatestPayload(null));
  }, [history]);

  useEffect(() => {
    if (!tenantId) return;
    fetch(`${CP_BASE}/api/returns/approved-snapshot-versions?tenant_id=${encodeURIComponent(tenantId)}`)
      .then((r) => r.json())
      .then((j: { items?: SnapshotPipelineVersion[] }) => {
        const rows = Array.isArray(j.items) ? j.items : [];
        setSnapshotVersions(rows);
        setSelectedPvId((cur) => (cur && rows.some((x) => x.id === cur) ? cur : rows[0]?.id ?? ""));
      })
      .catch(() => setSnapshotVersions([]));
  }, [tenantId]);

  if (!facilityId) return <main className="p-6 max-w-6xl mx-auto">Loading…</main>;
  if (!tenantId) return <main className="p-6 max-w-6xl mx-auto">Missing tenant_id query parameter.</main>;

  return (
    <main className="p-6 max-w-6xl mx-auto">
      <div className="mb-6">
        <Link href="/returns" className="text-sm text-blue-600 dark:text-blue-400 hover:underline">
          ← Facility returns home
        </Link>
      </div>
      <h1 className="text-xl font-bold mb-1">Facility returns</h1>
      <p className="text-sm text-gray-500 font-mono break-all mb-6">{facilityId}</p>

      <section className="mb-8 rounded border border-gray-200 dark:border-gray-700 p-4">
        <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-2">Run returns snapshot</h2>
        <div className="space-y-3 max-w-xl">
          {snapshotVersions.length > 1 && (
            <select value={selectedPvId} onChange={(e) => setSelectedPvId(e.target.value)} className="w-full px-2 py-2 rounded border">
              {snapshotVersions.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.pipeline_name ?? v.pipeline_id} / {v.version}
                </option>
              ))}
            </select>
          )}
          <input value={fixtureOverride} onChange={(e) => setFixtureOverride(e.target.value)} placeholder="Fixture override (optional)" className="w-full px-2 py-2 rounded border font-mono text-xs" />
          {triggerError && <p className="text-red-600 text-sm">{triggerError}</p>}
          <button
            type="button"
            disabled={triggerSubmitting || !selectedPvId}
            onClick={async () => {
              setTriggerSubmitting(true);
              setTriggerError(null);
              try {
                const parameters: Record<string, string> = { facility_id: facilityId };
                if (fixtureOverride.trim()) parameters.fixture = fixtureOverride.trim();
                const res = await fetch(`${CP_BASE}/api/runs`, {
                  method: "POST",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({ tenant_id: tenantId, pipeline_version_id: selectedPvId, trigger_type: "manual", parameters }),
                });
                const j = await res.json().catch(() => ({}));
                if (!res.ok) throw new Error(typeof j.detail === "string" ? j.detail : "Failed to create run");
                if (j.id) router.push(`/runs/${j.id}`);
              } catch (e) {
                setTriggerError(e instanceof Error ? e.message : "Failed to create run");
              } finally {
                setTriggerSubmitting(false);
              }
            }}
            className="px-4 py-2 rounded bg-blue-200 text-blue-900 text-sm font-medium disabled:opacity-40"
          >
            {triggerSubmitting ? "Creating…" : "Queue snapshot run"}
          </button>
        </div>
      </section>

      {summary && (
        <section className="mb-8 rounded border border-gray-200 dark:border-gray-700 p-4 text-sm grid sm:grid-cols-2 gap-3">
          <div>Returns count: <span className="font-mono">{summary.returns_count}</span></div>
          <div>Total units: <span className="font-mono">{summary.total_units}</span></div>
          <div>Pending: <span className="font-mono">{summary.pending_count}</span></div>
          <div>Received: <span className="font-mono">{summary.received_count}</span></div>
          <div>Processed: <span className="font-mono">{summary.processed_count}</span></div>
          <div>Needs attention: <span className="font-mono">{summary.needs_attention_count}</span></div>
          <div className="sm:col-span-2">Oldest open age (days): <span className="font-mono">{summary.oldest_open_age_days ?? "—"}</span></div>
        </section>
      )}

      <section className="mb-8">
        <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-2">Current returns table</h2>
        <div className="overflow-x-auto rounded border border-gray-200 dark:border-gray-700">
          <table className="min-w-full text-sm">
            <thead className="bg-gray-100 dark:bg-gray-800 text-left">
              <tr>
                <th className="p-2">Return</th><th className="p-2">Order</th><th className="p-2">SKU</th><th className="p-2">Qty</th>
                <th className="p-2">Status</th><th className="p-2">Reason</th><th className="p-2">Received</th><th className="p-2">Processed</th><th className="p-2">Source run</th><th className="p-2">Provider</th>
              </tr>
            </thead>
            <tbody>
              {items.map((row) => (
                <tr key={row.return_id} className="border-t">
                  <td className="p-2 font-mono">{row.return_id}</td><td className="p-2 font-mono">{row.order_id ?? "—"}</td><td className="p-2 font-mono">{row.sku}</td><td className="p-2 font-mono">{row.quantity}</td>
                  <td className="p-2">{row.status}</td><td className="p-2">{row.reason_code ?? "—"}</td><td className="p-2">{formatDate(row.received_at)}</td><td className="p-2">{formatDate(row.processed_at)}</td>
                  <td className="p-2">{row.source_run_id ? <Link href={`/runs/${row.source_run_id}`} className="text-blue-600 hover:underline font-mono text-xs">{row.source_run_id.slice(0, 8)}…</Link> : "—"}</td>
                  <td className="p-2 font-mono text-xs">{row.source_provider ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="mb-8">
        <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-2">Latest snapshot insight</h2>
        {latestPayload ? <pre className="p-3 text-xs rounded border bg-gray-100 dark:bg-gray-800 overflow-x-auto">{JSON.stringify(latestPayload, null, 2)}</pre> : <p className="text-sm text-gray-500">No latest returns_summary artifact yet.</p>}
      </section>

      <section className="mb-8">
        <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-2">Recent returns snapshot runs</h2>
        <div className="overflow-x-auto rounded border border-gray-200 dark:border-gray-700">
          <table className="min-w-full text-sm">
            <thead className="bg-gray-100 dark:bg-gray-800 text-left">
              <tr><th className="p-2">Created</th><th className="p-2">Status</th><th className="p-2">Fixture</th><th className="p-2">Counts</th><th className="p-2">Run</th></tr>
            </thead>
            <tbody>
              {history.map((h) => (
                <tr key={h.run_id} className="border-t">
                  <td className="p-2">{formatDate(h.created_at)}</td>
                  <td className="p-2">{h.status}</td>
                  <td className="p-2 font-mono text-xs">{h.fixture_used ?? "—"}</td>
                  <td className="p-2 text-xs">R {h.returns_count ?? "—"} / U {h.total_units ?? "—"} / P {h.pending_count ?? "—"} / N {h.needs_attention_count ?? "—"}</td>
                  <td className="p-2"><Link href={`/runs/${h.run_id}`} className="text-blue-600 hover:underline font-mono text-xs">{h.run_id.slice(0, 8)}…</Link></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </main>
  );
}

export default function FacilityReturnsPage(props: { params: Promise<{ facilityId: string }> }) {
  return (
    <Suspense fallback={<main className="p-6 max-w-6xl mx-auto">Loading…</main>}>
      <Inner {...props} />
    </Suspense>
  );
}
