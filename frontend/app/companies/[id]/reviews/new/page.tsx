"use client";

import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";

export default function NewReviewPage() {
  const params = useParams();
  const router = useRouter();
  const companyId = params.id as string;
  const [type, setType] = useState<"ANNUAL_REVIEW" | "NEW_FACILITY" | "INCREASE" | "MONITORING">("ANNUAL_REVIEW");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const engagementRes = await api<{ id: string }>("/api/reviews/engagements", {
        method: "POST",
        body: { company_id: companyId, type },
      });
      const reviewRes = await api<{ id: string; version_id: string }>("/api/reviews/credit-reviews", {
        method: "POST",
        body: { engagement_id: engagementRes.id, base_currency: "ZAR" },
      });
      router.push(`/reviews/${reviewRes.id}`);
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create review");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="mx-auto max-w-md">
      <div className="card">
        <h1 className="text-2xl font-bold text-white">Start credit review</h1>
        <p className="mt-2 text-slate-400">Create an engagement and credit review for this company.</p>
        <form onSubmit={submit} className="mt-6 space-y-4">
          <div>
            <label className="block text-sm font-medium text-slate-300">Review type</label>
            <select
              value={type}
              onChange={(e) => setType(e.target.value as typeof type)}
              className="input mt-1"
            >
              <option value="ANNUAL_REVIEW">Annual credit review</option>
              <option value="NEW_FACILITY">New facility</option>
              <option value="INCREASE">Credit increase</option>
              <option value="MONITORING">Monitoring</option>
            </select>
          </div>
          {error && <p className="text-sm text-amber-400">{error}</p>}
          <div className="flex gap-3">
            <button type="submit" className="btn-primary" disabled={loading}>
              {loading ? "Creating…" : "Create review"}
            </button>
            <Link href={`/companies/${companyId}`} className="btn-secondary">
              Cancel
            </Link>
          </div>
        </form>
      </div>
    </div>
  );
}
