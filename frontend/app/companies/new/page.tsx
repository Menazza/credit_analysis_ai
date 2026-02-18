"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { api } from "@/lib/api";

export default function NewCompanyPage() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [sector, setSector] = useState("");
  const [ticker, setTicker] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const company = await api<{ id: string }>("/api/companies", {
        method: "POST",
        body: {
          name,
          sector: sector || undefined,
          ticker: ticker || undefined,
          is_listed: ticker ? "true" : "false",
        },
      });
      router.push(`/companies/${company.id}`);
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create company");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="mx-auto max-w-md">
      <div className="card">
        <h1 className="text-2xl font-bold text-white">Add company</h1>
        <p className="mt-2 text-slate-400">Create a JSE or private company to upload documents and run credit reviews.</p>
        <form onSubmit={submit} className="mt-6 space-y-4">
          <div>
            <label className="block text-sm font-medium text-slate-300">Company name *</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="input mt-1"
              required
              placeholder="e.g. Acme (Pty) Ltd"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-300">Sector</label>
            <input
              type="text"
              value={sector}
              onChange={(e) => setSector(e.target.value)}
              className="input mt-1"
              placeholder="e.g. Retail, Mining"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-300">Ticker (if listed)</label>
            <input
              type="text"
              value={ticker}
              onChange={(e) => setTicker(e.target.value)}
              className="input mt-1"
              placeholder="e.g. ACM"
            />
          </div>
          {error && <p className="text-sm text-amber-400">{error}</p>}
          <div className="flex gap-3">
            <button type="submit" className="btn-primary" disabled={loading}>
              {loading ? "Creating…" : "Create company"}
            </button>
            <Link href="/companies" className="btn-secondary">
              Cancel
            </Link>
          </div>
        </form>
      </div>
    </div>
  );
}
