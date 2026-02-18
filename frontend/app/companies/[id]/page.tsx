"use client";

import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import Link from "next/link";
import { api, type Company } from "@/lib/api";

type Engagement = {
  id: string;
  name: string | null;
  type: string;
  status: string;
  created_at: string | null;
};

export default function CompanyDetailPage() {
  const params = useParams();
  const router = useRouter();
  const id = params.id as string;
  const [company, setCompany] = useState<Company | null>(null);
  const [engagements, setEngagements] = useState<Engagement[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const token = typeof window !== "undefined" ? localStorage.getItem("access_token") : null;
    if (!token) {
      router.push("/login");
      return;
    }
    Promise.all([
      api<Company>(`/api/companies/${id}`),
      api<Engagement[]>(`/api/companies/${id}/engagements`),
    ])
      .then(([c, engs]) => {
        setCompany(c);
        setEngagements(engs);
      })
      .catch(() => setCompany(null))
      .finally(() => setLoading(false));
  }, [id, router]);

  if (loading || !company) {
    return (
      <div className="text-slate-400">
        {loading ? "Loading…" : "Company not found."}
      </div>
    );
  }

  return (
    <div className="space-y-8">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-white">{company.name}</h1>
          {company.ticker && <p className="text-slate-400">{company.ticker} · {company.sector || "—"}</p>}
        </div>
        <Link href="/companies" className="btn-secondary">
          Back to companies
        </Link>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <div className="card">
          <h2 className="text-lg font-semibold text-white">Engagements</h2>
          <p className="mt-1 text-sm text-slate-400">Credit review engagements for this company.</p>

          {engagements.length === 0 ? (
            <div className="mt-4 space-y-3">
              <p className="text-slate-400">No engagements yet for this company.</p>
              <Link href={`/companies/${id}/engagements/new`} className="btn-primary">
                Create engagement
              </Link>
            </div>
          ) : (
            <>
              <Link href={`/companies/${id}/engagements/new`} className="mt-4 inline-block btn-primary">
                Start new engagement
              </Link>
              <ul className="mt-4 space-y-2">
                {engagements.map((e) => (
                  <li
                    key={e.id}
                    className="flex items-center justify-between rounded border border-slate-700 bg-slate-900/50 px-3 py-2"
                  >
                    <Link href={`/engagements/${e.id}`} className="text-primary-400 hover:underline">
                      {e.name ||
                        e.type
                          .replaceAll("_", " ")
                          .toLowerCase()
                          .replace(/^\w/, (c) => c.toUpperCase())}
                    </Link>
                    <span className="text-xs text-slate-500">{e.status}</span>
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
