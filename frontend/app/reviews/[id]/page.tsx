"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

type Version = {
  id: string;
  credit_review_id: string;
  version_no: string;
  locked_at: string | null;
  created_at: string | null;
};

type ReviewDetail = {
  id: string;
  engagement_id: string;
  company_id: string;
  review_period_end: string | null;
  base_currency: string;
  status: string;
  analysis_status: string | null;
  rating_grade: string | null;
  pd_band: number | null;
  key_metrics: Record<string, number> | null;
};

export default function ReviewDetailPage() {
  const params = useParams();
  const id = params.id as string;
  const [versions, setVersions] = useState<Version[]>([]);
  const [review, setReview] = useState<ReviewDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [downloading, setDownloading] = useState<string | null>(null);

  useEffect(() => {
    const token = typeof window !== "undefined" ? localStorage.getItem("access_token") : null;
    if (!token) return;

    // Load basic review status + versions, then poll status while analysis runs.
    const load = async () => {
      try {
        const [detail, vers] = await Promise.all([
          api<ReviewDetail>(`/api/reviews/credit-reviews/${id}`),
          api<Version[]>(`/api/reviews/credit-reviews/${id}/versions`),
        ]);
        setReview(detail);
        setVersions(vers);
      } catch {
        setReview(null);
        setVersions([]);
      } finally {
        setLoading(false);
      }
    };

    void load();

    // Poll for status while analysis is in progress
    const interval = setInterval(() => {
      api<ReviewDetail>(`/api/reviews/credit-reviews/${id}`)
        .then(setReview)
        .catch(() => undefined);
    }, 5000);

    return () => clearInterval(interval);
  }, [id]);

  const downloadMemo = async (versionId: string) => {
    const token = localStorage.getItem("access_token");
    if (!token) return;
    setDownloading(versionId);
    try {
      const res = await fetch(`${API_BASE}/api/export/credit-review/${versionId}/memo`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error("Download failed");
      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `credit-memo-${versionId}.docx`;
      a.click();
      window.URL.revokeObjectURL(url);
    } finally {
      setDownloading(null);
    }
  };

  if (loading) return <div className="text-slate-400">Loading review…</div>;
  if (!review) return <div className="text-slate-400">Credit review not found.</div>;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-3xl font-bold text-white">Credit review</h1>
        <Link href="/companies" className="btn-secondary">
          Back to companies
        </Link>
      </div>

      <div className="card space-y-2">
        <p className="text-sm text-slate-300">
          Company: <span className="font-mono text-slate-100">{review.company_id}</span>
        </p>
        <p className="text-sm text-slate-300">
          Review period end:{" "}
          <span className="font-mono text-slate-100">
            {review.review_period_end || "Not set"}
          </span>
        </p>
        <p className="text-sm text-slate-300">
          Status:{" "}
          <span className="font-semibold text-primary-300">
            {review.analysis_status || review.status}
          </span>
        </p>
        {review.analysis_status === "IN_REVIEW" && (
          <div className="mt-2 rounded-md bg-slate-900/60 px-3 py-2 text-sm text-slate-300">
            <p className="font-semibold text-primary-200">Running full credit review…</p>
            <ul className="mt-1 list-disc space-y-0.5 pl-5 text-slate-400 text-xs">
              <li>Parsing mapped financials and building normalized dataset</li>
              <li>Calculating leverage, coverage, liquidity and cash flow metrics</li>
              <li>Scoring quantitative and qualitative drivers to derive internal rating</li>
              <li>Preparing credit memo sections and export pack</li>
            </ul>
          </div>
        )}
        {!review.analysis_status && review.rating_grade && (
          <div className="mt-2 rounded-md bg-slate-900/60 px-3 py-2 text-sm text-slate-300">
            <p className="font-semibold text-primary-200">
              Internal rating: {review.rating_grade}
              {typeof review.pd_band === "number" && (
                <span className="ml-2 text-xs text-slate-400">(PD band: {review.pd_band})</span>
              )}
            </p>
            {review.key_metrics && (
              <div className="mt-1 grid gap-2 text-xs text-slate-300 sm:grid-cols-2 md:grid-cols-3">
                {Object.entries(review.key_metrics).map(([key, value]) => (
                  <div key={key} className="rounded bg-slate-950/60 px-2 py-1">
                    <div className="text-[11px] uppercase tracking-wide text-slate-500">
                      {key.replaceAll("_", " ")}
                    </div>
                    <div className="font-mono text-xs text-slate-100">{value.toFixed(2)}</div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      <div className="card">
        <h2 className="text-lg font-semibold text-white">Versions</h2>
        <p className="mt-1 text-sm text-slate-400">Download the credit memo (Word) for any version.</p>
        <ul className="mt-4 space-y-2">
          {versions.map((v) => (
            <li
              key={v.id}
              className="flex items-center justify-between rounded border border-slate-700 bg-slate-900/50 px-4 py-3"
            >
              <span className="text-slate-200">Version {v.version_no}</span>
              <button
                type="button"
                onClick={() => downloadMemo(v.id)}
                disabled={downloading === v.id}
                className="btn-primary text-sm"
              >
                {downloading === v.id ? "Downloading…" : "Download memo (.docx)"}
              </button>
            </li>
          ))}
          {versions.length === 0 && <li className="text-slate-500">No versions yet.</li>}
        </ul>
      </div>
    </div>
  );
}
