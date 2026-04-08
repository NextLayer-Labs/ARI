"use client";

import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";

const CP_BASE =
  (typeof process !== "undefined" && process.env.NEXT_PUBLIC_CP_BASE) ||
  "http://localhost:8000";

function shortId(id: string, len = 8): string {
  return id.length > len ? `${id.slice(0, len)}…` : id;
}

function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return String(iso);
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

type RunSummary = {
  run_id: string;
  status: string;
  created_at?: string | null;
  finished_at?: string | null;
  fixture_used?: string | null;
  items_total?: number;
  out_of_stock?: number;
};

type SkuChange = {
  sku: string;
  change_kind: string;
  on_hand_a: number | null;
  on_hand_b: number | null;
  available_a: number | null;
  available_b: number | null;
  delta_on_hand: number;
};

type CompareResult = {
  tenant_id: string;
  facility_id: string;
  run_id_a: string;
  run_id_b: string;
  summary_a: RunSummary;
  summary_b: RunSummary;
  changed_skus_count: number;
  unchanged_skus_count: number;
  new_skus_count: number;
  removed_skus_count: number;
  new_out_of_stock_count: number;
  back_in_stock_count: number;
  total_on_hand_a: number;
  total_on_hand_b: number;
  total_on_hand_delta: number;
  sku_changes: SkuChange[];
  sku_changes_total: number;
  sku_changes_truncated: boolean;
  new_out_of_stock_skus_sample: string[];
  back_in_stock_skus_sample: string[];
  source: string;
};

function CompareInner() {
  const searchParams = useSearchParams();
  const tenantId = searchParams.get("tenant_id")?.trim() || "";
  const runIdA = searchParams.get("run_id_a")?.trim() || "";
  const runIdB = searchParams.get("run_id_b")?.trim() || "";

  const [data, setData] = useState<CompareResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!tenantId || !runIdA || !runIdB) {
      setData(null);
      setError(null);
      return;
    }
    setLoading(true);
    setError(null);
    const u = new URL(`${CP_BASE}/api/inventory/compare-runs`);
    u.searchParams.set("tenant_id", tenantId);
    u.searchParams.set("run_id_a", runIdA);
    u.searchParams.set("run_id_b", runIdB);
    fetch(u.toString())
      .then(async (res) => {
        const j = await res.json().catch(() => ({}));
        if (!res.ok) {
          const d = j.detail;
          const msg =
            typeof d === "object" && d !== null && "message" in d
              ? String((d as { message: string }).message)
              : typeof d === "string"
                ? d
                : `HTTP ${res.status}`;
          throw new Error(msg);
        }
        return j as CompareResult;
      })
      .then(setData)
      .catch((e: Error) => {
        setData(null);
        setError(e.message || "Compare failed");
      })
      .finally(() => setLoading(false));
  }, [tenantId, runIdA, runIdB]);

  const facilityHref = `/inventory/${encodeURIComponent(data?.facility_id || "")}?tenant_id=${encodeURIComponent(tenantId)}`;

  return (
    <main className="p-6 max-w-6xl mx-auto">
      <div className="mb-4 flex flex-wrap gap-3 text-sm">
        <Link href="/inventory" className="text-blue-600 dark:text-blue-400 hover:underline">
          ← Inventory home
        </Link>
        {data?.facility_id && (
          <Link href={facilityHref} className="text-blue-600 dark:text-blue-400 hover:underline">
            Facility inventory
          </Link>
        )}
      </div>

      <h1 className="text-xl font-bold mb-2">Compare inventory snapshots</h1>
      <p className="text-sm text-gray-600 dark:text-gray-400 mb-6">
        Baseline run A (older) → run B (newer). Diff uses each run’s{" "}
        <strong>raw ingest fixture items</strong>, not live canonical inventory.
      </p>

      {!tenantId || !runIdA || !runIdB ? (
        <p className="text-amber-700 dark:text-amber-300 text-sm">
          Pass <code className="font-mono">tenant_id</code>,{" "}
          <code className="font-mono">run_id_a</code>, and{" "}
          <code className="font-mono">run_id_b</code> query parameters (A = older snapshot, B =
          newer).
        </p>
      ) : loading ? (
        <p className="text-gray-500">Loading comparison…</p>
      ) : error ? (
        <p className="text-red-600 dark:text-red-400 text-sm" role="alert">
          {error}
        </p>
      ) : data ? (
        <>
          <section className="mb-6 text-sm">
            <h2 className="text-sm font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-2">
              Context
            </h2>
            <dl className="grid grid-cols-[minmax(8rem,auto)_1fr] gap-x-3 gap-y-1">
              <dt className="text-gray-500">Tenant</dt>
              <dd className="font-mono text-xs break-all">{data.tenant_id}</dd>
              <dt className="text-gray-500">Facility</dt>
              <dd className="font-mono text-xs break-all">{data.facility_id}</dd>
              <dt className="text-gray-500">Source</dt>
              <dd className="font-mono text-xs">{data.source}</dd>
            </dl>
          </section>

          <section className="mb-6 grid md:grid-cols-2 gap-4">
            <div className="rounded border border-gray-200 dark:border-gray-700 p-3 text-sm">
              <h3 className="font-semibold mb-2 text-gray-600 dark:text-gray-300">Run A (baseline)</h3>
              <div className="space-y-1">
                <div className="flex flex-wrap gap-2 items-center">
                  <span className={statusBadgeClass(data.summary_a.status)}>{data.summary_a.status}</span>
                  <Link
                    href={`/runs/${data.run_id_a}`}
                    className="font-mono text-xs text-blue-600 dark:text-blue-400 hover:underline"
                  >
                    {shortId(data.run_id_a)}
                  </Link>
                </div>
                <div>Created: {formatDate(data.summary_a.created_at)}</div>
                <div>Finished: {formatDate(data.summary_a.finished_at)}</div>
                <div>Fixture: {data.summary_a.fixture_used ?? "—"}</div>
                <div>
                  Items: {data.summary_a.items_total ?? "—"} · OOS:{" "}
                  {data.summary_a.out_of_stock ?? "—"}
                </div>
              </div>
            </div>
            <div className="rounded border border-gray-200 dark:border-gray-700 p-3 text-sm">
              <h3 className="font-semibold mb-2 text-gray-600 dark:text-gray-300">Run B</h3>
              <div className="space-y-1">
                <div className="flex flex-wrap gap-2 items-center">
                  <span className={statusBadgeClass(data.summary_b.status)}>{data.summary_b.status}</span>
                  <Link
                    href={`/runs/${data.run_id_b}`}
                    className="font-mono text-xs text-blue-600 dark:text-blue-400 hover:underline"
                  >
                    {shortId(data.run_id_b)}
                  </Link>
                </div>
                <div>Created: {formatDate(data.summary_b.created_at)}</div>
                <div>Finished: {formatDate(data.summary_b.finished_at)}</div>
                <div>Fixture: {data.summary_b.fixture_used ?? "—"}</div>
                <div>
                  Items: {data.summary_b.items_total ?? "—"} · OOS:{" "}
                  {data.summary_b.out_of_stock ?? "—"}
                </div>
              </div>
            </div>
          </section>

          <section className="mb-6 rounded border border-gray-200 dark:border-gray-700 p-4 text-sm">
            <h2 className="text-sm font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-3">
              Summary counts
            </h2>
            <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-2">
              <div>Changed SKUs: {data.changed_skus_count}</div>
              <div>Unchanged SKUs: {data.unchanged_skus_count}</div>
              <div>New in B: {data.new_skus_count}</div>
              <div>Removed in B: {data.removed_skus_count}</div>
              <div>New OOS (both runs): {data.new_out_of_stock_count}</div>
              <div>Back in stock: {data.back_in_stock_count}</div>
              <div>
                Total on-hand A → B: {data.total_on_hand_a} → {data.total_on_hand_b} (Δ{" "}
                {data.total_on_hand_delta > 0 ? "+" : ""}
                {data.total_on_hand_delta})
              </div>
            </div>
            {(data.new_out_of_stock_skus_sample.length > 0 ||
              data.back_in_stock_skus_sample.length > 0) && (
              <div className="mt-3 pt-3 border-t border-gray-200 dark:border-gray-700 text-xs space-y-1">
                {data.new_out_of_stock_skus_sample.length > 0 && (
                  <div>
                    <span className="text-gray-500">New OOS sample:</span>{" "}
                    <span className="font-mono">{data.new_out_of_stock_skus_sample.join(", ")}</span>
                  </div>
                )}
                {data.back_in_stock_skus_sample.length > 0 && (
                  <div>
                    <span className="text-gray-500">Back in stock sample:</span>{" "}
                    <span className="font-mono">{data.back_in_stock_skus_sample.join(", ")}</span>
                  </div>
                )}
              </div>
            )}
          </section>

          <section className="mb-6">
            <h2 className="text-sm font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-2">
              SKU changes (largest |Δ on-hand| first)
            </h2>
            {data.sku_changes_truncated && (
              <p className="text-xs text-amber-700 dark:text-amber-300 mb-2">
                Showing {data.sku_changes.length} of {data.sku_changes_total} changed/new/removed rows.
              </p>
            )}
            {data.sku_changes.length === 0 ? (
              <p className="text-sm text-gray-500">No SKU-level differences (same item set and quantities).</p>
            ) : (
              <div className="overflow-x-auto rounded border border-gray-200 dark:border-gray-700">
                <table className="min-w-full text-sm">
                  <thead className="bg-gray-100 dark:bg-gray-800 text-left">
                    <tr>
                      <th className="p-2 font-medium">SKU</th>
                      <th className="p-2 font-medium">Kind</th>
                      <th className="p-2 font-medium">on_hand A</th>
                      <th className="p-2 font-medium">on_hand B</th>
                      <th className="p-2 font-medium">Δ</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.sku_changes.map((row) => (
                      <tr key={row.sku} className="border-t border-gray-200 dark:border-gray-700">
                        <td className="p-2 font-mono">{row.sku}</td>
                        <td className="p-2 text-xs">{row.change_kind}</td>
                        <td className="p-2 font-mono">{row.on_hand_a ?? "—"}</td>
                        <td className="p-2 font-mono">{row.on_hand_b ?? "—"}</td>
                        <td className="p-2 font-mono">
                          {row.delta_on_hand > 0 ? "+" : ""}
                          {row.delta_on_hand}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      ) : null}
    </main>
  );
}

export default function ComparePage() {
  return (
    <Suspense
      fallback={
        <main className="p-6 max-w-5xl mx-auto">
          <p className="text-gray-500">Loading…</p>
        </main>
      }
    >
      <CompareInner />
    </Suspense>
  );
}
