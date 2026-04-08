"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

const CP_BASE =
  (typeof process !== "undefined" && process.env.NEXT_PUBLIC_CP_BASE) ||
  "http://localhost:8000";

type FacilityRow = {
  id: string;
  tenant_id: string;
  name: string;
  facility_type: string;
};

export default function ReturnsIndexPage() {
  const [tenantId, setTenantId] = useState("");
  const [facilities, setFacilities] = useState<FacilityRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [manualFacilityId, setManualFacilityId] = useState("");

  useEffect(() => {
    if (!tenantId.trim()) {
      setFacilities([]);
      return;
    }
    setLoading(true);
    setError(null);
    const u = new URL(`${CP_BASE}/api/facilities`);
    u.searchParams.set("tenant_id", tenantId.trim());
    u.searchParams.set("limit", "200");
    fetch(u.toString())
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
      })
      .then((data: { items?: FacilityRow[] }) => {
        setFacilities(Array.isArray(data.items) ? data.items : []);
      })
      .catch(() => {
        setError("Could not load facilities. Check tenant ID and API.");
        setFacilities([]);
      })
      .finally(() => setLoading(false));
  }, [tenantId]);

  return (
    <main className="p-6 max-w-3xl mx-auto">
      <h1 className="text-xl font-bold mb-2">Facility returns</h1>
      <p className="text-sm text-gray-600 dark:text-gray-400 mb-6">
        Enter a tenant ID to list facilities, then open the returns queue for a facility.
      </p>

      <section className="mb-8 space-y-3">
        <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">Tenant ID</label>
        <input
          type="text"
          value={tenantId}
          onChange={(e) => setTenantId(e.target.value)}
          placeholder="Paste tenant UUID"
          className="w-full px-3 py-2 rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 font-mono text-sm"
        />
        {loading && <p className="text-sm text-gray-500">Loading facilities…</p>}
        {error && <p className="text-sm text-amber-600 dark:text-amber-400">{error}</p>}
        {tenantId.trim() && !loading && !error && facilities.length === 0 && (
          <p className="text-sm text-gray-500">No facilities for this tenant.</p>
        )}
        {facilities.length > 0 && (
          <ul className="border border-gray-200 dark:border-gray-700 rounded divide-y divide-gray-200 dark:divide-gray-700">
            {facilities.map((f) => (
              <li key={f.id} className="px-3 py-2 flex flex-wrap items-center justify-between gap-2">
                <span className="font-medium">{f.name}</span>
                <span className="font-mono text-xs text-gray-500 break-all">{f.id}</span>
                <Link
                  href={`/returns/${encodeURIComponent(f.id)}?tenant_id=${encodeURIComponent(f.tenant_id)}`}
                  className="text-sm text-blue-600 dark:text-blue-400 hover:underline shrink-0"
                >
                  View returns →
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="border-t border-gray-200 dark:border-gray-700 pt-6">
        <h2 className="text-sm font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-2">
          Open by facility ID
        </h2>
        <div className="flex flex-col sm:flex-row gap-2 items-stretch sm:items-center">
          <input
            type="text"
            value={manualFacilityId}
            onChange={(e) => setManualFacilityId(e.target.value)}
            placeholder="Facility UUID"
            className="flex-1 px-3 py-2 rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 font-mono text-sm"
          />
          {tenantId.trim() && manualFacilityId.trim() && (
            <Link
              href={`/returns/${encodeURIComponent(manualFacilityId.trim())}?tenant_id=${encodeURIComponent(tenantId.trim())}`}
              className="inline-flex justify-center px-4 py-2 rounded bg-blue-200 text-blue-900 dark:bg-blue-900 dark:text-blue-100 text-sm font-medium hover:opacity-90"
            >
              Go
            </Link>
          )}
        </div>
      </section>

      <p className="mt-8 text-sm">
        <Link href="/runs" className="text-blue-600 dark:text-blue-400 hover:underline">
          ← Back to runs
        </Link>
      </p>
    </main>
  );
}
