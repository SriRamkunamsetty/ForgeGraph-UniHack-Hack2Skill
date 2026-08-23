"use client";

import { ChangeEvent, useState } from "react";

const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8080";

type Job = {
  id: string;
  status: string;
  filename: string;
  input_sha256: string;
  reference_pack_version: string;
  quality: {
    total_rows: number;
    processed_rows: number;
    accepted_rows: number;
    review_rows: number;
    failed_rows: number;
    evidence_coverage: number;
  };
};

export default function HomePage() {
  const [file, setFile] = useState<File | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [message, setMessage] = useState("Upload a supplier CSV or XLSX to begin.");
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file) {
      setMessage("Select a CSV or XLSX file first.");
      return;
    }
    setBusy(true);
    setMessage("Processing the file through the ForgeGraph validation pipeline…");
    const body = new FormData();
    body.append("file", file);
    try {
      const response = await fetch(`${apiBase}/api/v1/catalog/jobs`, { method: "POST", body });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail ?? "Unable to create catalog job");
      setJob(payload);
      setMessage("Job completed through the first vertical slice. Evidence and category extraction are next.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unexpected error");
    } finally {
      setBusy(false);
    }
  }

  function onFileChange(event: ChangeEvent<HTMLInputElement>) {
    setFile(event.target.files?.[0] ?? null);
    setJob(null);
  }

  return (
    <main className="shell">
      <header className="topbar">
        <div className="brand"><span className="brand-mark">F</span><span>ForgeGraph</span></div>
        <span className="status-pill">Production foundation</span>
      </header>

      <section className="hero">
        <div>
          <p className="eyebrow">INDUSTRIAL PRODUCT INTELLIGENCE</p>
          <h1>From sparse supplier data to trusted product truth.</h1>
          <p className="hero-copy">ForgeGraph enriches industrial catalogs with controlled AI, manufacturer evidence, deterministic validation, and human review.</p>
        </div>
        <div className="hero-note"><strong>Core principle</strong><br />The model proposes claims. The quality firewall decides what can be published.</div>
      </section>

      <section className="workspace-grid">
        <div className="card upload-card">
          <div className="section-heading"><div><p className="eyebrow">01 · INGEST</p><h2>Start a catalog job</h2></div><span className="step-number">01</span></div>
          <p className="muted">The input is preserved with a SHA-256 hash before normalization begins.</p>
          <form onSubmit={submit}>
            <label className="dropzone">
              <input type="file" accept=".csv,.xlsx" onChange={onFileChange} />
              <span className="drop-icon">↑</span>
              <strong>{file ? file.name : "Choose supplier file"}</strong>
              <small>CSV or XLSX · 25 MB configured limit</small>
            </label>
            <button className="primary-button" type="submit" disabled={busy}>{busy ? "Processing…" : "Create intelligence job"}</button>
          </form>
          <p className="message" role="status">{message}</p>
        </div>

        <div className="card quality-card">
          <div className="section-heading"><div><p className="eyebrow">02 · QUALITY</p><h2>Trust dashboard</h2></div><span className="live-dot">LIVE</span></div>
          <div className="metric-grid">
            <Metric label="Rows processed" value={job ? `${job.quality.processed_rows}` : "—"} />
            <Metric label="Review required" value={job ? `${job.quality.review_rows}` : "—"} />
            <Metric label="Blocked rows" value={job ? `${job.quality.failed_rows}` : "—"} />
            <Metric label="Evidence coverage" value={job ? `${Math.round(job.quality.evidence_coverage * 100)}%` : "—"} />
          </div>
          {job && <div className="job-meta"><span>Job {job.id.slice(0, 8)}</span><span className="job-status">{job.status}</span></div>}
          {!job && <div className="empty-state">Run a file to see row-level quality, review rate, and evidence coverage.</div>}
        </div>
      </section>

      <section className="capability-row">
        <Capability title="Evidence-backed" body="Every important technical value can point to a source and evidence span." />
        <Capability title="Controlled AI" body="Structured claims are checked against ontology, LOV, UOM, and business rules." />
        <Capability title="Human-ready" body="Ambiguity and conflict become review tasks instead of hidden errors." />
      </section>
      <footer>Zen Z · Mohan Sriram Kunamsetty · ForgeGraph</footer>
    </main>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return <div className="metric"><span>{label}</span><strong>{value}</strong></div>;
}

function Capability({ title, body }: { title: string; body: string }) {
  return <article className="capability"><span className="capability-line" /><div><h3>{title}</h3><p>{body}</p></div></article>;
}
