"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";

type DocumentVersionSummary = {
  id: string;
  document_id: string;
  status: string;
  sha256: string | null;
  created_at: string | null;
  doc_type: string;
  original_filename: string;
  engagement_id: string | null;
};

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function downloadExtractedFiles(versionId: string, filename: string) {
  const token = typeof window !== "undefined" ? localStorage.getItem("access_token") : null;
  const res = await fetch(
    `${API_BASE}/api/documents/versions/${versionId}/download-extracted`,
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
  a.download = `extracted_${filename.replace(".pdf", "")}.zip`;
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
  const [downloading, setDownloading] = useState(false);

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

  const handleDownload = async () => {
    if (!summary) return;
    setDownloading(true);
    try {
      await downloadExtractedFiles(id, summary.original_filename);
    } catch (err) {
      alert(err instanceof Error ? err.message : "Download failed");
    } finally {
      setDownloading(false);
    }
  };

  if (loading) return <div className="text-slate-400 p-8">Loading document analysis…</div>;
  if (error) return <div className="text-amber-400 p-8">{error}</div>;
  if (!summary) return <div className="text-slate-400 p-8">Document version not found.</div>;

  return (
    <div className="max-w-2xl mx-auto p-8 space-y-8">
      <div className="text-center space-y-2">
        <h1 className="text-3xl font-bold text-white">Extraction Complete</h1>
        <p className="text-slate-400">Your financial statements and notes have been extracted.</p>
      </div>

      <div className="card p-6 space-y-4">
        <div className="space-y-2 text-sm">
          <div className="flex justify-between">
            <span className="text-slate-400">File:</span>
            <span className="font-mono text-slate-100">{summary.original_filename}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-slate-400">Type:</span>
            <span className="text-slate-100">{summary.doc_type}</span>
          </div>
          <div className="flex justify-between">
            <span className="text-slate-400">Status:</span>
            <span className={`font-semibold ${summary.status === "MAPPED" ? "text-green-400" : "text-primary-300"}`}>
              {summary.status}
            </span>
          </div>
        </div>

        <div className="border-t border-slate-700 pt-4">
          <p className="text-sm text-slate-400 mb-4">
            Download contains: Excel file with all statements, JSON file with notes, and notes summary.
          </p>
          <button
            type="button"
            onClick={handleDownload}
            disabled={downloading || summary.status !== "MAPPED"}
            className="w-full btn-primary py-3 text-lg disabled:opacity-50"
          >
            {downloading ? "Preparing download..." : "Download Extracted Files"}
          </button>
        </div>
      </div>

      <div className="flex justify-center gap-4">
        {summary.engagement_id && (
          <Link 
            href={`/engagements/${summary.engagement_id}`}
            className="btn-secondary"
          >
            ← Back to Engagement
          </Link>
        )}
        <Link href="/companies" className="btn-secondary">
          Back to Companies
        </Link>
      </div>
    </div>
  );
}
