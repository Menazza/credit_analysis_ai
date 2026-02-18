import Link from "next/link";

export default function HomePage() {
  return (
    <div className="space-y-12">
      <section className="text-center">
        <h1 className="text-4xl font-bold tracking-tight text-white sm:text-5xl">
          Credit Analysis AI
        </h1>
        <p className="mx-auto mt-4 max-w-2xl text-lg text-slate-400">
          Bank-grade corporate credit review platform: upload AFS, extract financials,
          map to a canonical model, run validations, compute metrics and ratings,
          and generate audit-ready credit packs.
        </p>
      </section>
      <section className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
        <Link href="/companies" className="card block transition hover:border-primary-500/50">
          <h2 className="text-xl font-semibold text-primary-400">Companies</h2>
          <p className="mt-2 text-slate-400">
            JSE and private companies. Create companies, attach documents, run reviews.
          </p>
        </Link>
        <Link href="/companies?journey=review" className="card block transition hover:border-primary-500/50">
          <h2 className="text-xl font-semibold text-primary-400">Annual credit review</h2>
          <p className="mt-2 text-slate-400">
            Load last review, upload latest AFS and MA, refresh extraction, generate memo and pack.
          </p>
        </Link>
        <Link href="/companies?journey=facility" className="card block transition hover:border-primary-500/50">
          <h2 className="text-xl font-semibold text-primary-400">New facility / increase</h2>
          <p className="mt-2 text-slate-400">
            Full onboarding, facility terms, repayment capacity, security, recommendation.
          </p>
        </Link>
        <Link href="/portfolios" className="card block transition hover:border-primary-500/50">
          <h2 className="text-xl font-semibold text-primary-400">Portfolios</h2>
          <p className="mt-2 text-slate-400">
            Group companies into portfolios for monitoring and reporting.
          </p>
        </Link>
        <div className="card">
          <h2 className="text-xl font-semibold text-slate-300">Monitoring</h2>
          <p className="mt-2 text-slate-400">
            Monthly/quarterly uploads, covenant tracking, triggers, watchlist.
          </p>
        </div>
        <div className="card">
          <h2 className="text-xl font-semibold text-slate-300">Audit trail</h2>
          <p className="mt-2 text-slate-400">
            Every number traceable to evidence (page, bbox, source file). Versioned outputs.
          </p>
        </div>
      </section>
    </div>
  );
}
