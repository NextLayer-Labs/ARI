"use client";

import { useState, useCallback } from "react";
import { useRouter } from "next/navigation";

const CP_BASE =
  (typeof process !== "undefined" && process.env.NEXT_PUBLIC_CP_BASE) ||
  "http://localhost:8000";

type RunCreateResponse = {
  id: string;
  tenant_id: string;
  pipeline_version_id: string;
  status: string;
  trigger_type?: string;
  parameters?: Record<string, unknown>;
};

function parseParametersJson(value: string): { ok: true; data: Record<string, unknown> } | { ok: false; error: string } {
  const trimmed = value.trim();
  if (trimmed === "") return { ok: true, data: {} };
  try {
    const parsed = JSON.parse(trimmed);
    if (parsed === null || Array.isArray(parsed) || typeof parsed !== "object") {
      return { ok: false, error: "Parameters must be a JSON object (e.g. {} or {\"key\": \"value\"})." };
    }
    return { ok: true, data: parsed as Record<string, unknown> };
  } catch {
    return { ok: false, error: "Invalid JSON. Parameters must be a valid JSON object." };
  }
}

type TriggerRunButtonProps = {
  tenantId: string;
  pipelineVersionId: string;
  label?: string;
  disabled?: boolean;
  className?: string;
};

export function TriggerRunButton({
  tenantId,
  pipelineVersionId,
  label = "Run",
  disabled = false,
  className = "px-2 py-1 text-xs font-medium rounded bg-blue-200 text-blue-800 dark:bg-blue-900 dark:text-blue-200 hover:bg-blue-300 dark:hover:bg-blue-800",
}: TriggerRunButtonProps) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [parametersText, setParametersText] = useState("{}");
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const handleOpen = useCallback(() => {
    setOpen(true);
    setParametersText("{}");
    setSubmitError(null);
  }, []);

  const handleClose = useCallback(() => {
    if (!submitting) {
      setOpen(false);
      setSubmitError(null);
    }
  }, [submitting]);

  const handleSubmit = useCallback(
    async (e: React.FormEvent) => {
      e.preventDefault();
      const parsed = parseParametersJson(parametersText);
      if (!parsed.ok) {
        setSubmitError(parsed.error);
        return;
      }
      setSubmitError(null);
      setSubmitting(true);
      try {
        const res = await fetch(`${CP_BASE}/api/runs`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            tenant_id: tenantId,
            pipeline_version_id: pipelineVersionId,
            parameters: parsed.data,
          }),
        });
        const json = await res.json().catch(() => ({}));
        if (!res.ok) {
          const msg =
            typeof json.detail === "string"
              ? json.detail
              : Array.isArray(json.detail)
                ? json.detail.map((x: { msg?: string }) => x.msg ?? JSON.stringify(x)).join("; ")
                : json.reason ?? `HTTP ${res.status}`;
          setSubmitError(msg);
          setSubmitting(false);
          return;
        }
        const run = json as RunCreateResponse;
        if (run?.id) {
          router.push(`/runs/${run.id}`);
          return;
        }
        setSubmitError("No run id in response");
      } catch (err) {
        setSubmitError(err instanceof Error ? err.message : "Request failed");
      } finally {
        setSubmitting(false);
      }
    },
    [tenantId, pipelineVersionId, parametersText, router]
  );

  return (
    <>
      <button
        type="button"
        onClick={handleOpen}
        disabled={disabled}
        className={className}
      >
        {label}
      </button>

      {open && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50"
          onClick={handleClose}
          role="dialog"
          aria-modal="true"
          aria-labelledby="trigger-run-title"
        >
          <div
            className="bg-white dark:bg-gray-900 rounded-lg shadow-xl max-w-md w-full border border-gray-200 dark:border-gray-700"
            onClick={(e) => e.stopPropagation()}
          >
            <h2 id="trigger-run-title" className="text-lg font-semibold px-4 pt-4">
              Trigger run
            </h2>
            <p className="text-sm text-gray-500 dark:text-gray-400 px-4 mt-1">
              Creates a QUEUED run for this pipeline version. You will be redirected to the run page.
            </p>
            <form onSubmit={handleSubmit} className="p-4 space-y-3">
              <label className="block text-sm font-medium">
                Parameters <span className="text-gray-500 font-normal">(JSON object)</span>
              </label>
              <textarea
                value={parametersText}
                onChange={(e) => setParametersText(e.target.value)}
                rows={6}
                className="w-full px-3 py-2 border border-gray-300 dark:border-gray-600 rounded bg-white dark:bg-gray-800 font-mono text-sm"
                placeholder="{}"
                spellCheck={false}
                disabled={submitting}
              />
              {submitError && (
                <p className="text-sm text-red-600 dark:text-red-400" role="alert">
                  {submitError}
                </p>
              )}
              <div className="flex gap-2 justify-end pt-2">
                <button
                  type="button"
                  onClick={handleClose}
                  disabled={submitting}
                  className="px-3 py-1.5 text-sm rounded border border-gray-300 dark:border-gray-600"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={submitting}
                  className="px-3 py-1.5 text-sm font-medium rounded bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50"
                >
                  {submitting ? "Creating run…" : "Create run"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </>
  );
}
