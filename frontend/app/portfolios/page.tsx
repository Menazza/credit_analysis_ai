"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";

type Portfolio = { id: string; name: string };

export default function PortfoliosPage() {
  const [portfolios, setPortfolios] = useState<Portfolio[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const token = typeof window !== "undefined" ? localStorage.getItem("access_token") : null;
    if (!token) {
      setLoading(false);
      setError("Please log in.");
      return;
    }
    api<Portfolio[]>("/api/portfolios")
      .then(setPortfolios)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="text-slate-400">Loading portfolios…</div>;
  if (error) {
    return (
      <div className="card border-amber-500/30">
        <p className="text-amber-200">{error}</p>
        <Link href="/login" className="mt-4 inline-block text-primary-400 hover:underline">Login</Link>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-3xl font-bold text-white">Portfolios</h1>
      </div>
      <div className="card">
        {portfolios.length === 0 ? (
          <p className="text-slate-400">No portfolios. Create one from the API or add a create form here.</p>
        ) : (
          <ul className="divide-y divide-slate-700">
            {portfolios.map((p) => (
              <li key={p.id} className="py-4 first:pt-0 last:pb-0">
                <Link href={`/companies?portfolio_id=${p.id}`} className="font-medium text-primary-400 hover:underline">
                  {p.name}
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
