"use client";

import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";

type EngagementResponse = {
  id: string;
  company_id: string;
  name: string | null;
  type: string;
};

export default function NewEngagementPage() {
  const params = useParams();
  const router = useRouter();
  const companyId = params.id as string;
  const [name, setName] = useState("");
  const [type, setType] = useState<"ANNUAL_REVIEW" | "NEW_FACILITY" | "INCREASE" | "MONITORING">("ANNUAL_REVIEW");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) {
      setError("Please enter an engagement name.");
      return;
    }
    setError(null);
    setLoading(true);
    try {
      const engagement = await api<EngagementResponse>("/api/reviews/engagements", {
        method: "POST",
        body: { company_id: companyId, type, name: name.trim() },
      });
      router.push(`/engagements/${engagement.id}`);
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create engagement");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="mx-auto max-w-md">
      <div className="card">
        <h1 className="text-2xl font-bold text-white">Start new engagement</h1>
        <p className="mt-2 text-slate-400">Give the engagement a name and select the overall type.</p>
        <form onSubmit={submit} className="mt-6 space-y-4">
          <div>
            <label className="block text-sm font-medium text-slate-300">Engagement name</label>
            <input
              className="input mt-1 w-full"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. FY25 Annual review"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-300">Engagement type</label>
            <select
              value={type}
              onChange={(e) => setType(e.target.value as typeof type)}
              className="input mt-1 w-full"
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
              {loading ? "Creating…" : "Create engagement"}
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

