"use client";

import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import Link from "next/link";
import { api, apiUpload, type DocumentVersion } from "@/lib/api";

type Engagement = {
  id: string;
  company_id: string;
  name: string | null;
  type: string;
  status: string;
  created_at: string | null;
};

type Doc = {
  id: string;
  company_id: string;
  doc_type: string;
  original_filename: string;
  storage_url: string | null;
  uploaded_at: string | null;
  latest_version_id?: string | null;
};

type CreditReviewCreateResponse = {
  id: string;
  engagement_id: string;
  review_period_end: string | null;
  base_currency: string;
  status: string;
  version_id: string;
  version_no: string;
};

export default function EngagementDetailPage() {
  const params = useParams();
  const id = params.id as string;
  const [engagement, setEngagement] = useState<Engagement | null>(null);
  const [documents, setDocuments] = useState<Doc[]>([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [uploadDocType, setUploadDocType] = useState("AFS");
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [startingReview, setStartingReview] = useState(false);
  const [startError, setStartError] = useState<string | null>(null);

  useEffect(() => {
    const token = typeof window !== "undefined" ? localStorage.getItem("access_token") : null;
    if (!token) return;

    api<Engagement>(`/api/reviews/engagements/${id}`)
      .then(async (eng) => {
        setEngagement(eng);
        const docs = await api<Doc[]>(
          `/api/documents?company_id=${eng.company_id}&engagement_id=${eng.id}`
        );
        setDocuments(docs);
      })
      .catch(() => {
        setEngagement(null);
        setDocuments([]);
      })
      .finally(() => setLoading(false));
  }, [id]);

  const onUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !engagement) return;
    setUploading(true);
    setUploadError(null);
    const form = new FormData();
    form.append("company_id", engagement.company_id);
    form.append("engagement_id", engagement.id);
    form.append("doc_type", uploadDocType);
    form.append("file", file);
    try {
      const v: DocumentVersion = await apiUpload("/api/documents/upload", form);
      setDocuments((prev) => [
        ...prev,
        {
          id: v.document_id,
          company_id: engagement.company_id,
          doc_type: uploadDocType,
          original_filename: file.name,
          storage_url: null,
          uploaded_at: v.created_at,
          latest_version_id: v.id,
        },
      ]);
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setUploading(false);
      e.target.value = "";
    }
  };

  const startCreditReview = async () => {
    if (!engagement) return;
    setStartingReview(true);
    setStartError(null);
    try {
      // 1) Create the credit review + first version
      const res = await api<CreditReviewCreateResponse>("/api/reviews/credit-reviews", {
        method: "POST",
        body: { engagement_id: engagement.id, base_currency: "ZAR" },
      });
      // 2) Kick off the analysis pipeline for this review (Celery engines)
      await api<{ review_id: string; version_id: string; status: string; message?: string }>(
        `/api/reviews/credit-reviews/${res.id}/run`,
        { method: "POST" }
      );
      // 3) Navigate to the review page where progress + memo download are available
      window.location.href = `/reviews/${res.id}`;
    } catch (err) {
      setStartError(err instanceof Error ? err.message : "Failed to start credit review");
      setStartingReview(false);
    }
  };

  if (loading) return <div className="text-slate-400">Loading engagement…</div>;
  if (!engagement) return <div className="text-slate-400">Engagement not found.</div>;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-white">
            {engagement.name || "Engagement"}
          </h1>
          <p className="text-slate-400 text-sm">
            {engagement.type
              .replaceAll("_", " ")
              .toLowerCase()
              .replace(/^\w/, (c) => c.toUpperCase())}{" "}
            · Status: {engagement.status}
          </p>
        </div>
        <Link href={`/companies/${engagement.company_id}`} className="btn-secondary">
          Back to company
        </Link>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <div className="card">
          <h2 className="text-lg font-semibold text-white">Documents</h2>
          <p className="mt-1 text-sm text-slate-400">
            Upload AFS, management accounts, debt schedule, covenant cert, forecasts for this engagement.
          </p>
          <div className="mt-4 flex flex-wrap items-center gap-3">
            <select
              value={uploadDocType}
              onChange={(e) => setUploadDocType(e.target.value)}
              className="input w-44"
            >
              <option value="AFS">AFS</option>
              <option value="MA">Management accounts</option>
              <option value="DEBT_SCHEDULE">Debt schedule</option>
              <option value="COV_CERT">Covenant cert</option>
              <option value="FORECAST">Forecast</option>
              <option value="OTHER">Other</option>
            </select>
            <label className="btn-primary cursor-pointer">
              <input
                type="file"
                className="hidden"
                accept=".pdf,.xlsx,.xls,.csv"
                onChange={onUpload}
                disabled={uploading}
              />
              {uploading ? "Uploading…" : "Upload file"}
            </label>
          </div>
          {uploadError && <p className="mt-2 text-sm text-amber-400">{uploadError}</p>}
          <ul className="mt-4 space-y-2">
            {documents.map((d) => (
              <li
                key={d.id}
                className="flex items-center justify-between rounded border border-slate-700 bg-slate-900/50 px-3 py-2"
              >
                <div>
                  <div className="text-slate-200">{d.original_filename}</div>
                  <div className="text-xs text-slate-500">{d.doc_type}</div>
                </div>
                {/* Prefer the latest version id when linking to analysis */}
                <Link
                  href={`/documents/${d.latest_version_id ?? d.id}`}
                  className="text-xs font-medium text-primary-300 hover:text-primary-200"
                >
                  View analysis
                </Link>
              </li>
            ))}
            {documents.length === 0 && <li className="text-slate-500">No documents uploaded yet.</li>}
          </ul>
        </div>

        <div className="card">
          <h2 className="text-lg font-semibold text-white">Run analysis</h2>
          <p className="mt-1 text-sm text-slate-400">
            Once documents are uploaded, start a credit review to generate analysis and a memo.
          </p>
          {startError && <p className="mt-3 text-sm text-amber-400">{startError}</p>}
          <button
            type="button"
            className="mt-4 btn-primary"
            onClick={startCreditReview}
            disabled={startingReview}
          >
            {startingReview ? "Starting credit review…" : "Start credit review"}
          </button>
          <p className="mt-2 text-xs text-slate-500">
            You will be taken to the review page where you can download the credit memo.
          </p>
        </div>
      </div>
    </div>
  );
}

