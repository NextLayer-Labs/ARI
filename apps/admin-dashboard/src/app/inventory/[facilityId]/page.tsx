"use client";

import { Suspense, useEffect, useState, useCallback } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";

const CP_BASE =
  (typeof process !== "undefined" && process.env.NEXT_PUBLIC_CP_BASE) ||
  "http://localhost:8000";

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

type FacilitySummary = {
  facility_id: string;
  tenant_id: string;
  sku_count: number;
  total_on_hand: number;
  out_of_stock_count: number;
  latest_as_of: string | null;
};

type HistoryRow = {
  run_id: string;
  pipeline_version_id: string;
  status: string;
  trigger_type: string;
  created_at: string | null;
  finished_at: string | null;
  fixture_used?: string | null;
  items_total?: number | null;
  out_of_stock?: number | null;
  changed_skus_count?: number | null;
  new_skus_count?: number | null;
  back_in_stock_count?: number | null;
  new_out_of_stock_count?: number | null;
  artifact_present?: boolean;
  top_deltas_sample?: Array<{
    sku: string;
    previous_on_hand: number;
    current_on_hand: number;
    delta_on_hand: number;
  }> | null;
};

type CanonItem = {
  sku: string;
  on_hand: number;
  available: number | null;
  reserved: number | null;
  as_of: string | null;
  source_provider: string | null;
  source_run_id: string | null;
};

type FacilityRawIngestRow = {
  id: string;
  run_id: string;
  provider: string;
  mapping_version: string;
  fetched_at: string | null;
  as_of: string | null;
  payload: Record<string, unknown>;
};

function FacilityInventoryInner({
  params,
}: {
  params: Promise<{ facilityId: string }>;
}) {
  const searchParams = useSearchParams();
  const tenantId = searchParams.get("tenant_id")?.trim() || "";

  const [facilityId, setFacilityId] = useState<string | null>(null);
  const [summary, setSummary] = useState<FacilitySummary | null>(null);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const [history, setHistory] = useState<HistoryRow[]>([]);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [items, setItems] = useState<CanonItem[]>([]);
  const [itemsTotal, setItemsTotal] = useState(0);
  const [itemsLimit] = useState(50);
  const [itemsOffset, setItemsOffset] = useState(0);
  const [itemsLoading, setItemsLoading] = useState(false);
  const [itemsError, setItemsError] = useState<string | null>(null);
  const [oosOnly, setOosOnly] = useState(false);
  const [rawIngests, setRawIngests] = useState<FacilityRawIngestRow[]>([]);
  const [rawIngestsError, setRawIngestsError] = useState<string | null>(null);
  const [rawFacilityOpenId, setRawFacilityOpenId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    params.then((p) => {
      if (!cancelled) setFacilityId(decodeURIComponent(p.facilityId));
    });
    return () => {
      cancelled = true;
    };
  }, [params]);

  const loadSummaryAndHistory = useCallback(async (fid: string, tid: string) => {
    setSummaryError(null);
    setHistoryError(null);
    const su = new URL(`${CP_BASE}/api/inventory/facility-summary`);
    su.searchParams.set("facility_id", fid);
    su.searchParams.set("tenant_id", tid);
    const hu = new URL(`${CP_BASE}/api/inventory/facility-history`);
    hu.searchParams.set("facility_id", fid);
    hu.searchParams.set("tenant_id", tid);
    hu.searchParams.set("limit", "40");

    const [sRes, hRes] = await Promise.all([fetch(su.toString()), fetch(hu.toString())]);
    if (!sRes.ok) {
      setSummary(null);
      setSummaryError(`Summary: ${sRes.status}`);
    } else {
      const sJson = await sRes.json();
      setSummary(sJson as FacilitySummary);
    }
    if (!hRes.ok) {
      setHistory([]);
      setHistoryError(`History: ${hRes.status}`);
    } else {
      const hJson = await hRes.json();
      setHistory(Array.isArray(hJson.items) ? hJson.items : []);
    }
  }, []);

  const loadItems = useCallback(
    async (fid: string, tid: string, offset: number, oos: boolean) => {
      setItemsLoading(true);
      setItemsError(null);
      const u = new URL(`${CP_BASE}/api/inventory/items`);
      u.searchParams.set("facility_id", fid);
      u.searchParams.set("tenant_id", tid);
      u.searchParams.set("limit", String(itemsLimit));
      u.searchParams.set("offset", String(offset));
      if (oos) u.searchParams.set("oos_only", "true");
      try {
        const res = await fetch(u.toString());
        if (!res.ok) {
          setItemsError(`Items: ${res.status}`);
          setItems([]);
          setItemsTotal(0);
          return;
        }
        const data = await res.json();
        setItems(Array.isArray(data.items) ? data.items : []);
        setItemsTotal(typeof data.count === "number" ? data.count : 0);
      } catch {
        setItemsError("Failed to load inventory items");
        setItems([]);
      } finally {
        setItemsLoading(false);
      }
    },
    [itemsLimit],
  );

  useEffect(() => {
    if (!facilityId || !tenantId) return;
    loadSummaryAndHistory(facilityId, tenantId);
  }, [facilityId, tenantId, loadSummaryAndHistory]);

  useEffect(() => {
    if (!facilityId || !tenantId) return;
    setRawIngestsError(null);
    const ru = new URL(`${CP_BASE}/api/inventory/raw-ingests`);
    ru.searchParams.set("tenant_id", tenantId);
    ru.searchParams.set("facility_id", facilityId);
    ru.searchParams.set("limit", "15");
    fetch(ru.toString())
      .then((res) => {
        if (!res.ok) {
          setRawIngests([]);
          setRawIngestsError(`Raw ingests: ${res.status}`);
          return;
        }
        return res.json();
      })
      .then((data: { items?: FacilityRawIngestRow[] } | undefined) => {
        if (!data) return;
        setRawIngests(Array.isArray(data.items) ? data.items : []);
        setRawIngestsError(null);
      })
      .catch(() => {
        setRawIngests([]);
        setRawIngestsError("Could not load raw ingests");
      });
  }, [facilityId, tenantId]);

  useEffect(() => {
    if (!facilityId || !tenantId) return;
    loadItems(facilityId, tenantId, itemsOffset, oosOnly);
  }, [facilityId, tenantId, itemsOffset, oosOnly, loadItems]);

  const latest = history.length > 0 ? history[0] : null;

  if (!facilityId) {
    return (
      <main className="p-6 max-w-5xl mx-auto">
        <p className="text-gray-500">Loading…</p>
      </main>
    );
  }

  if (!tenantId) {
    return (
      <main className="p-6 max-w-5xl mx-auto">
        <p className="text-amber-600 dark:text-amber-400 mb-4">
          Missing <code className="font-mono">tenant_id</code> query parameter. Open this page from{" "}
          <Link href="/inventory" className="text-blue-600 dark:text-blue-400 hover:underline">
            /inventory
          </Link>{" "}
          or use{" "}
          <span className="font-mono text-sm">
            /inventory/{facilityId}?tenant_id=&lt;tenant-uuid&gt;
          </span>
        </p>
        <Link href="/inventory" className="text-blue-600 dark:text-blue-400 hover:underline text-sm">
          ← Facility inventory home
        </Link>
      </main>
    );
  }

  const totalPages = Math.max(1, Math.ceil(itemsTotal / itemsLimit));
  const pageNum = Math.floor(itemsOffset / itemsLimit) + 1;

  return (
    <main className="p-6 max-w-6xl mx-auto">
      <div className="mb-6">
        <Link
          href="/inventory"
          className="text-sm text-blue-600 dark:text-blue-400 hover:underline"
        >
          ← Facility inventory home
        </Link>
      </div>
      <h1 className="text-xl font-bold mb-1">Facility inventory</h1>
      <p className="text-sm text-gray-500 dark:text-gray-400 font-mono break-all mb-6">
        {facilityId}
      </p>

      {/* A — Current summary (canonical, API aggregate) */}
      <section className="mb-8">
        <h2 className="text-sm font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-2">
          Current state (canonical)
        </h2>
        {summaryError && (
          <p className="text-amber-600 dark:text-amber-400 text-sm mb-2">{summaryError}</p>
        )}
        {summary && !summaryError ? (
          <div className="rounded border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900/40 p-4 text-sm grid sm:grid-cols-2 gap-3">
            <div>
              <span className="text-gray-500 dark:text-gray-400">Tenant</span>
              <div className="font-mono text-xs break-all">{summary.tenant_id}</div>
            </div>
            <div>
              <span className="text-gray-500 dark:text-gray-400">SKUs</span>
              <div className="font-mono">{summary.sku_count}</div>
            </div>
            <div>
              <span className="text-gray-500 dark:text-gray-400">Total on-hand</span>
              <div className="font-mono">{Number(summary.total_on_hand)}</div>
            </div>
            <div>
              <span className="text-gray-500 dark:text-gray-400">Out of stock</span>
              <div className="font-mono">{summary.out_of_stock_count}</div>
            </div>
            <div className="sm:col-span-2">
              <span className="text-gray-500 dark:text-gray-400">Latest as_of (canonical)</span>
              <div>{summary.latest_as_of ? formatDate(summary.latest_as_of) : "—"}</div>
            </div>
          </div>
        ) : !summaryError ? (
          <p className="text-sm text-gray-500">Loading summary…</p>
        ) : null}
      </section>

      {/* B — Table */}
      <section className="mb-8">
        <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
          <h2 className="text-sm font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide">
            Inventory rows (canonical)
          </h2>
          <label className="flex items-center gap-2 text-sm cursor-pointer">
            <input
              type="checkbox"
              checked={oosOnly}
              onChange={(e) => {
                setItemsOffset(0);
                setOosOnly(e.target.checked);
              }}
            />
            Out of stock only
          </label>
        </div>
        {itemsError && <p className="text-amber-600 text-sm mb-2">{itemsError}</p>}
        {itemsLoading && <p className="text-sm text-gray-500">Loading items…</p>}
        {!itemsLoading && items.length === 0 && !itemsError && (
          <p className="text-sm text-gray-500">No rows for this facility.</p>
        )}
        {items.length > 0 && (
          <div className="overflow-x-auto rounded border border-gray-200 dark:border-gray-700">
            <table className="min-w-full text-sm">
              <thead className="bg-gray-100 dark:bg-gray-800 text-left">
                <tr>
                  <th className="p-2 font-medium">SKU</th>
                  <th className="p-2 font-medium">On hand</th>
                  <th className="p-2 font-medium">Avail</th>
                  <th className="p-2 font-medium">Resv</th>
                  <th className="p-2 font-medium">As of</th>
                  <th className="p-2 font-medium">Provider</th>
                  <th className="p-2 font-medium">Source run</th>
                </tr>
              </thead>
              <tbody>
                {items.map((row) => (
                  <tr
                    key={row.sku}
                    className="border-t border-gray-200 dark:border-gray-700"
                  >
                    <td className="p-2 font-mono">{row.sku}</td>
                    <td className="p-2 font-mono">{row.on_hand}</td>
                    <td className="p-2 font-mono">{row.available ?? "—"}</td>
                    <td className="p-2 font-mono">{row.reserved ?? "—"}</td>
                    <td className="p-2 whitespace-nowrap">{row.as_of ? formatDate(row.as_of) : "—"}</td>
                    <td className="p-2 font-mono text-xs">{row.source_provider ?? "—"}</td>
                    <td className="p-2">
                      {row.source_run_id ? (
                        <Link
                          href={`/runs/${row.source_run_id}`}
                          className="font-mono text-xs text-blue-600 dark:text-blue-400 hover:underline"
                          title={row.source_run_id}
                        >
                          {shortId(row.source_run_id)}
                        </Link>
                      ) : (
                        "—"
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {itemsTotal > itemsLimit && (
          <div className="mt-3 flex flex-wrap items-center gap-3 text-sm">
            <span className="text-gray-500">
              Page {pageNum} / {totalPages} ({itemsTotal} rows)
            </span>
            <button
              type="button"
              disabled={itemsOffset === 0}
              onClick={() => setItemsOffset(Math.max(0, itemsOffset - itemsLimit))}
              className="px-2 py-1 rounded border border-gray-300 dark:border-gray-600 disabled:opacity-40"
            >
              Previous
            </button>
            <button
              type="button"
              disabled={itemsOffset + itemsLimit >= itemsTotal}
              onClick={() => setItemsOffset(itemsOffset + itemsLimit)}
              className="px-2 py-1 rounded border border-gray-300 dark:border-gray-600 disabled:opacity-40"
            >
              Next
            </button>
          </div>
        )}
      </section>

      {/* Latest snapshot insight (sits above run history; same data as first history row) */}
      {latest && (
        <section className="mb-8">
          <h2 className="text-sm font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-2">
            Latest snapshot insight
          </h2>
          <div className="rounded border border-gray-200 dark:border-gray-700 p-4 text-sm space-y-2">
            <div className="flex flex-wrap gap-2 items-center">
              <span className={statusBadgeClass(latest.status)}>{latest.status}</span>
              <span className="text-gray-500">Run {shortId(latest.run_id)}</span>
              <Link
                href={`/runs/${latest.run_id}`}
                className="text-blue-600 dark:text-blue-400 hover:underline text-sm"
              >
                Open run →
              </Link>
            </div>
            <div className="text-gray-600 dark:text-gray-300">
              Created: {formatDate(latest.created_at)} · Finished: {formatDate(latest.finished_at)}
            </div>
            {latest.fixture_used != null && latest.fixture_used !== "" && (
              <div>
                <span className="text-gray-500">Fixture:</span>{" "}
                <span className="font-mono">{latest.fixture_used}</span>
              </div>
            )}
            <div className="flex flex-wrap gap-x-4 gap-y-1">
              {typeof latest.items_total === "number" && (
                <span>Items: {latest.items_total}</span>
              )}
              {typeof latest.out_of_stock === "number" && (
                <span>OOS: {latest.out_of_stock}</span>
              )}
              {typeof latest.changed_skus_count === "number" && (
                <span>Changed SKUs: {latest.changed_skus_count}</span>
              )}
              {typeof latest.new_skus_count === "number" && (
                <span>New SKUs: {latest.new_skus_count}</span>
              )}
            </div>
            {(latest.new_out_of_stock_count != null || latest.back_in_stock_count != null) && (
              <div className="text-xs text-gray-600 dark:text-gray-400">
                New OOS sample count: {latest.new_out_of_stock_count ?? "—"} · Back in stock sample
                count: {latest.back_in_stock_count ?? "—"}
              </div>
            )}
            {Array.isArray(latest.top_deltas_sample) && latest.top_deltas_sample.length > 0 && (
              <div>
                <p className="text-gray-500 text-xs mb-1">Top deltas (sample)</p>
                <ul className="font-mono text-xs space-y-0.5">
                  {latest.top_deltas_sample.slice(0, 5).map((d) => (
                    <li key={d.sku}>
                      {d.sku}: {d.previous_on_hand} → {d.current_on_hand} ({d.delta_on_hand > 0 ? "+" : ""}
                      {d.delta_on_hand})
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {!latest.artifact_present && (
              <p className="text-xs text-amber-700 dark:text-amber-300">No inventory_summary artifact yet.</p>
            )}
          </div>
        </section>
      )}

      {/* Recent history */}
      <section className="mb-8">
        <h2 className="text-sm font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-2">
          Recent inventory snapshot runs
        </h2>
        {historyError && (
          <p className="text-amber-600 dark:text-amber-400 text-sm mb-2">{historyError}</p>
        )}
        {history.length === 0 && !historyError ? (
          <p className="text-sm text-gray-500">No inventory snapshot runs recorded for this facility.</p>
        ) : (
          <div className="overflow-x-auto rounded border border-gray-200 dark:border-gray-700">
            <table className="min-w-full text-sm">
              <thead className="bg-gray-100 dark:bg-gray-800 text-left">
                <tr>
                  <th className="p-2 font-medium">Created</th>
                  <th className="p-2 font-medium">Status</th>
                  <th className="p-2 font-medium">Fixture</th>
                  <th className="p-2 font-medium">Items</th>
                  <th className="p-2 font-medium">OOS</th>
                  <th className="p-2 font-medium">Δ chg</th>
                  <th className="p-2 font-medium">New</th>
                  <th className="p-2 font-medium">OOS↔</th>
                  <th className="p-2 font-medium">Run</th>
                </tr>
              </thead>
              <tbody>
                {history.map((h) => (
                  <tr key={h.run_id} className="border-t border-gray-200 dark:border-gray-700">
                    <td className="p-2 whitespace-nowrap">{formatDate(h.created_at)}</td>
                    <td className="p-2">
                      <span className={statusBadgeClass(h.status)}>{h.status}</span>
                    </td>
                    <td className="p-2 font-mono text-xs max-w-[8rem] truncate" title={h.fixture_used ?? ""}>
                      {h.fixture_used ?? "—"}
                    </td>
                    <td className="p-2 font-mono">{h.items_total ?? "—"}</td>
                    <td className="p-2 font-mono">{h.out_of_stock ?? "—"}</td>
                    <td className="p-2 font-mono">{h.changed_skus_count ?? "—"}</td>
                    <td className="p-2 font-mono">{h.new_skus_count ?? "—"}</td>
                    <td className="p-2 text-xs">
                      ΔOOS {h.new_out_of_stock_count ?? "—"} / BI {h.back_in_stock_count ?? "—"}
                    </td>
                    <td className="p-2">
                      <Link
                        href={`/runs/${h.run_id}`}
                        className="text-blue-600 dark:text-blue-400 hover:underline font-mono text-xs"
                      >
                        {shortId(h.run_id)}
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Raw ingests (facility-wide, any run) */}
      <section className="mb-8">
        <h2 className="text-sm font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-2">
          Raw ingests (recent)
        </h2>
        <p className="text-xs text-gray-500 dark:text-gray-400 mb-2">
          Provider payloads stored for this facility (newest first). Use run detail for a single run’s rows only.
        </p>
        {rawIngestsError && (
          <p className="text-amber-600 dark:text-amber-400 text-sm mb-2">{rawIngestsError}</p>
        )}
        {rawIngests.length === 0 && !rawIngestsError ? (
          <p className="text-sm text-gray-500">No raw ingests recorded for this facility.</p>
        ) : (
          <div className="space-y-2">
            {rawIngests.map((row) => (
              <div
                key={row.id}
                className="rounded border border-gray-200 dark:border-gray-700 text-sm overflow-hidden"
              >
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 bg-gray-50 dark:bg-gray-900/40">
                  <span className="text-gray-500 dark:text-gray-400 whitespace-nowrap">
                    {formatDate(row.fetched_at)}
                  </span>
                  <span className="font-mono text-xs">{row.provider}</span>
                  <Link
                    href={`/runs/${row.run_id}`}
                    className="text-xs text-blue-600 dark:text-blue-400 hover:underline font-mono"
                    title={row.run_id}
                  >
                    run {shortId(row.run_id)}
                  </Link>
                  <button
                    type="button"
                    onClick={() =>
                      setRawFacilityOpenId((x) => (x === row.id ? null : row.id))
                    }
                    className="text-xs text-blue-600 dark:text-blue-400 hover:underline ml-auto"
                  >
                    {rawFacilityOpenId === row.id ? "Hide payload" : "View payload"}
                  </button>
                </div>
                {rawFacilityOpenId === row.id && (
                  <pre className="p-3 text-xs overflow-x-auto max-h-64 overflow-y-auto bg-gray-100 dark:bg-gray-800 border-t border-gray-200 dark:border-gray-700">
                    {JSON.stringify(row.payload ?? {}, null, 2)}
                  </pre>
                )}
              </div>
            ))}
          </div>
        )}
      </section>
    </main>
  );
}

export default function FacilityInventoryPage(props: {
  params: Promise<{ facilityId: string }>;
}) {
  return (
    <Suspense
      fallback={
        <main className="p-6 max-w-5xl mx-auto">
          <p className="text-gray-500">Loading…</p>
        </main>
      }
    >
      <FacilityInventoryInner {...props} />
    </Suspense>
  );
}
