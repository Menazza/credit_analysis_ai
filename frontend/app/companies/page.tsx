"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api, type Company } from "@/lib/api";

export default function CompaniesPage() {
  const [companies, setCompanies] = useState<Company[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const token = typeof window !== "undefined" ? localStorage.getItem("access_token") : null;
    if (!token) {
      setLoading(false);
      setError("Please log in to view companies.");
      return;
    }
    api<Company[]>("/api/companies")
      .then(setCompanies)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="text-slate-400">Loading companies…</div>;
  if (error) {
    return (
      <div className="card border-amber-500/30 bg-amber-950/20">
        <p className="text-amber-200">{error}</p>
        <Link href="/login" className="mt-4 inline-block text-primary-400 hover:underline">
          Go to login
        </Link>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-3xl font-bold text-white">Companies</h1>
        <Link href="/companies/new" className="btn-primary">
          Add company
        </Link>
      </div>
      <div className="card">
        {companies.length === 0 ? (
          <p className="text-slate-400">No companies yet. Add a company to upload documents and run credit reviews.</p>
        ) : (
          <ul className="divide-y divide-slate-700">
            {companies.map((c) => (
              <li key={c.id} className="py-4 first:pt-0 last:pb-0">
                <Link href={`/companies/${c.id}`} className="block hover:bg-slate-800/50 -mx-2 rounded-lg px-2 py-2">
                  <span className="font-medium text-white">{c.name}</span>
                  {c.ticker && <span className="ml-2 text-slate-400">({c.ticker})</span>}
                  {c.sector && <span className="ml-2 text-slate-500">— {c.sector}</span>}
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
