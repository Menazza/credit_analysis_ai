"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";

type MappingRow = {
  raw_label?: string;
  canonical_key?: string;
  confidence?: number;
};

type NoteRow = {
  note_number?: string;
  title?: string;
  note_type?: string;
};

type DocumentVersionSummary = {
  id: string;
  document_id: string;
  status: string;
  sha256: string | null;
  created_at: string | null;
  doc_type: string;
  original_filename: string;
  presentation_scale: Record<string, unknown> | null;
  canonical_mappings: { mappings?: MappingRow[] } | null;
  note_classifications: { notes?: NoteRow[] } | null;
};

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function downloadLlmInput(versionId: string) {
  const data = await api<unknown>(`/api/documents/versions/${versionId}/llm-input`);
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `llm-input-${versionId}.json`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

async function downloadStatements(versionId: string, format: "csv" | "xlsx") {
  const token = typeof window !== "undefined" ? localStorage.getItem("access_token") : null;
  const res = await fetch(
    `${API_BASE}/api/documents/versions/${versionId}/export?format=${format}`,
    { headers: token ? { Authorization: `Bearer ${token}` } : {} }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || res.statusText);
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `statements-${versionId}.${format}`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export default function DocumentVersionDetailPage() {
  const params = useParams();
  const id = params.id as string;
  const [summary, setSummary] = useState<DocumentVersionSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const token = typeof window !== "undefined" ? localStorage.getItem("access_token") : null;
    if (!token) return;

    api<DocumentVersionSummary>(`/api/documents/versions/${id}/summary`)
      .then((data) => {
        setSummary(data);
        setError(null);
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : "Failed to load document summary");
        setSummary(null);
      })
      .finally(() => setLoading(false));
  }, [id]);

  if (loading) return <div className="text-slate-400">Loading document analysis…</div>;
  if (error) return <div className="text-amber-400">{error}</div>;
  if (!summary) return <div className="text-slate-400">Document version not found.</div>;

  const mappings = summary.canonical_mappings?.mappings ?? [];
  const notes = summary.note_classifications?.notes ?? [];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-4">
        <h1 className="text-2xl font-bold text-white">Document analysis</h1>
        <div className="flex items-center gap-2">
          <button
            type="button"
            className="btn-secondary"
            onClick={() => downloadStatements(id, "csv")}
          >
            Download CSV
          </button>
          <button
            type="button"
            className="btn-secondary"
            onClick={() => downloadStatements(id, "xlsx")}
          >
            Download Excel
          </button>
          <button
            type="button"
            className="btn-secondary"
            onClick={() => downloadLlmInput(id)}
          >
            Download raw LLM input
          </button>
          <Link href="/companies" className="btn-secondary">
            Back to companies
          </Link>
        </div>
      </div>

      <div className="card space-y-1 text-sm text-slate-300">
        <p>
          <span className="font-semibold">File:</span>{" "}
          <span className="font-mono text-slate-100">{summary.original_filename}</span>
        </p>
        <p>
          <span className="font-semibold">Type:</span> {summary.doc_type}
        </p>
        <p>
          <span className="font-semibold">Status:</span>{" "}
          <span className="font-semibold text-primary-300">{summary.status}</span>
        </p>
        {summary.presentation_scale && (
          <p className="mt-1 text-xs text-slate-400">
            Presentation scale detected:{" "}
            <code className="rounded bg-slate-900/60 px-1 py-0.5 text-xs text-slate-200">
              {JSON.stringify(summary.presentation_scale)}
            </code>
          </p>
        )}
      </div>

      <div className="card">
        <h2 className="text-lg font-semibold text-white">Mapped line items</h2>
        <p className="mt-1 text-sm text-slate-400">
          Raw labels detected in the statements and their mapped canonical accounts. Confidence below internal
          thresholds may be flagged as UNMAPPED.
        </p>
        <div className="mt-3 max-h-72 overflow-auto rounded border border-slate-800">
          <table className="min-w-full text-left text-xs">
            <thead className="bg-slate-900/80 text-slate-300">
              <tr>
                <th className="px-3 py-2">Raw label</th>
                <th className="px-3 py-2">Canonical key</th>
                <th className="px-3 py-2 text-right">Confidence</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800 bg-slate-950/40">
              {mappings.map((m, idx) => (
                <tr key={idx}>
                  <td className="px-3 py-1.5 text-slate-100">{m.raw_label || "-"}</td>
                  <td className="px-3 py-1.5 font-mono text-xs text-primary-300">
                    {m.canonical_key || "UNMAPPED"}
                  </td>
                  <td className="px-3 py-1.5 text-right text-slate-300">
                    {typeof m.confidence === "number" ? `${(m.confidence * 100).toFixed(0)}%` : "-"}
                  </td>
                </tr>
              ))}
              {mappings.length === 0 && (
                <tr>
                  <td colSpan={3} className="px-3 py-3 text-center text-slate-500">
                    No canonical mappings available yet. Ensure extraction and mapping have completed.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      <div className="card">
        <h2 className="text-lg font-semibold text-white">Notes overview</h2>
        <p className="mt-1 text-sm text-slate-400">
          Key notes identified in the AFS or supporting documents, with their titles and types where classified.
        </p>
        <ul className="mt-3 space-y-2 text-sm">
          {notes.map((n, idx) => (
            <li
              key={idx}
              className="rounded border border-slate-800 bg-slate-950/40 px-3 py-2 text-slate-200"
            >
              <div className="flex items-center justify-between">
                <span className="font-semibold">
                  Note {n.note_number || "?"}: {n.title || "(Untitled)"}
                </span>
                {n.note_type && (
                  <span className="rounded-full bg-slate-900 px-2 py-0.5 text-xs uppercase tracking-wide text-slate-300">
                    {n.note_type}
                  </span>
                )}
              </div>
            </li>
          ))}
          {notes.length === 0 && (
            <li className="text-slate-500 text-sm">
              No note classifications available yet. They will appear here once note extraction has run.
            </li>
          )}
        </ul>
      </div>
    </div>
  );
}

