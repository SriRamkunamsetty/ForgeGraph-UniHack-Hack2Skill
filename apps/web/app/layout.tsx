import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "ForgeGraph | Industrial Product Intelligence",
  description:
    "Evidence-backed product truth for industrial commerce. AI-governed catalog intelligence with claim-level provenance, deterministic validation, and human review workflows.",
  keywords: [
    "industrial commerce",
    "product intelligence",
    "catalog management",
    "AI product data",
    "claim validation",
    "ForgeGraph",
  ],
  authors: [{ name: "Zen Z Team" }],
  openGraph: {
    title: "ForgeGraph | Industrial Product Intelligence",
    description: "Evidence-backed product truth for industrial commerce.",
    type: "website",
  },
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className="antialiased">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link
          rel="preconnect"
          href="https://fonts.gstatic.com"
          crossOrigin="anonymous"
        />
      </head>
      <body className="min-h-screen bg-slate-50 text-slate-900 font-sans">
        {children}
      </body>
    </html>
  );
}
