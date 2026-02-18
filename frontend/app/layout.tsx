import type { Metadata } from "next";
import "./globals.css";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Credit Analysis AI",
  description: "Bank-grade corporate credit review platform",
};

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="dark">
      <body className="min-h-screen bg-slate-950 text-slate-100 antialiased">
        <header className="sticky top-0 z-50 border-b border-slate-800 bg-slate-950/95 backdrop-blur">
          <div className="mx-auto flex h-14 max-w-7xl items-center justify-between px-4">
            <Link href="/" className="text-lg font-semibold text-primary-400">
              Credit Analysis AI
            </Link>
            <nav className="flex items-center gap-6">
              <Link href="/companies" className="text-slate-300 hover:text-white">
                Companies
              </Link>
              <Link href="/portfolios" className="text-slate-300 hover:text-white">
                Portfolios
              </Link>
              <Link href="/login" className="text-slate-300 hover:text-white">
                Login
              </Link>
            </nav>
          </div>
        </header>
        <main className="mx-auto max-w-7xl px-4 py-8">{children}</main>
      </body>
    </html>
  );
}
