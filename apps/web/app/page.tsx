"use client";

import { ChangeEvent, useState } from "react";

const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL ?? "https://forgegraph-api-root.vercel.app";
const tenantId = process.env.NEXT_PUBLIC_TENANT_ID ?? "local";
const terminalStatuses = new Set(["completed", "waiting_review", "failed", "cancelled"]);

type Quality = {
  total_rows: number;
  processed_rows: number;
  accepted_rows: number;
  review_rows: number;
  failed_rows: number;
  claims_total: number;
  claims_with_evidence: number;
  validation_errors: number;
  evidence_coverage: number;
};

type Job = {
  id: string;
  status: string;
  filename: string;
  input_sha256: string;
  reference_pack_version: string;
  quality: Quality;
  error?: string | null;
};

type ReviewTask = {
  id: string;
  product_id: string;
  risk: number;
  status: string;
  payload: {
    mpn?: string;
    manufacturer?: string;
    brand?: string;
    raw?: Record<string, unknown>;
    validations?: Array<{ message: string }>;
  };
};

async function apiRequest(path: string, options: RequestInit = {}) {
  const headers = new Headers(options.headers);
  headers.set("X-Tenant-ID", tenantId);
  const response = await fetch(`${apiBase}${path}`, { ...options, headers });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.detail ?? `Request failed (${response.status})`);
  return payload;
}

function wait(milliseconds: number) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

export default function HomePage() {
  const [file, setFile] = useState<File | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [reviews, setReviews] = useState<ReviewTask[]>([]);
  const [message, setMessage] = useState("Upload a supplier CSV or XLSX to begin.");
  const [busy, setBusy] = useState(false);

  async function loadJobDetails(jobId: string) {
    const [latestJob, latestReviews] = await Promise.all([
      apiRequest(`/api/v1/catalog/jobs/${jobId}`),
      apiRequest(`/api/v1/reviews?status=open`),
    ]);
    setJob(latestJob);
    setReviews(latestReviews.filter((task: ReviewTask) => task.payload));
    return latestJob as Job;
  }

  async function pollJob(jobId: string) {
    for (let attempt = 0; attempt < 90; attempt += 1) {
      const latestJob = await loadJobDetails(jobId);
      if (terminalStatuses.has(latestJob.status)) return latestJob;
      await wait(2000);
    }
    throw new Error("The job is still running. Refresh shortly to see its final status.");
  }

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file) {
      setMessage("Select a CSV or XLSX file first.");
      return;
    }
    setBusy(true);
    setReviews([]);
    setMessage("Uploading the immutable source artifact…");
    const body = new FormData();
    body.append("file", file);
    try {
      const created = (await apiRequest("/api/v1/catalog/jobs", { method: "POST", body })) as Job;
      setJob(created);
      setMessage(
        created.status === "created" || created.status === "running"
          ? "Job accepted. Durable workers are processing the catalog…"
          : "Catalog processed. Loading claims and review tasks…",
      );
      const latest = terminalStatuses.has(created.status) ? await loadJobDetails(created.id) : await pollJob(created.id);
      setMessage(
        latest.status === "waiting_review"
          ? "Processing complete. High-risk or unsupported records are ready for review."
          : latest.status === "completed"
            ? "Processing complete. The quality firewall accepted the catalog."
            : latest.error ?? `Job ended with status ${latest.status}.`,
      );
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unexpected error");
    } finally {
      setBusy(false);
    }
  }

  async function decide(taskId: string, decision: "approved" | "rejected") {
    try {
      await apiRequest(`/api/v1/reviews/${taskId}/decision`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Actor": "operator" },
        body: JSON.stringify({ decision }),
      });
      if (job) await loadJobDetails(job.id);
      setMessage(`Review task ${decision}. The decision is recorded in the audit trail.`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Unable to save review decision");
    }
  }

  function onFileChange(event: ChangeEvent<HTMLInputElement>) {
    setFile(event.target.files?.[0] ?? null);
    setJob(null);
    setReviews([]);
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
          <p className="muted">The input is preserved in object storage with a SHA-256 identity before normalization begins.</p>
          <form onSubmit={submit}>
            <label className="dropzone">
              <input type="file" accept=".csv,.xlsx" onChange={onFileChange} />
              <span className="drop-icon">↑</span>
              <strong>{file ? file.name : "Choose supplier file"}</strong>
              <small>CSV or XLSX · configured size and row limits</small>
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
          {job && <div className="job-meta"><span>Job {job.id.slice(0, 8)} · {job.filename}</span><span className="job-status">{job.status}</span></div>}
          {!job && <div className="empty-state">Run a file to see row-level quality, review rate, and evidence coverage.</div>}
          {job && <div className="export-actions"><a href={`${apiBase}/api/v1/catalog/jobs/${job.id}/export.csv`} target="_blank" rel="noreferrer">Download CSV</a><a href={`${apiBase}/api/v1/catalog/jobs/${job.id}/export.xlsx`} target="_blank" rel="noreferrer">Download XLSX</a></div>}
        </div>
      </section>

      {job && <section className="detail-grid">
        <div className="card">
          <div className="section-heading"><div><p className="eyebrow">03 · CLAIM LEDGER</p><h2>Processing evidence</h2></div></div>
          <div className="ledger-row"><span>Input fingerprint</span><code>{job.input_sha256}</code></div>
          <div className="ledger-row"><span>Reference pack</span><strong>{job.reference_pack_version}</strong></div>
          <div className="ledger-row"><span>Claims generated</span><strong>{job.quality.claims_total}</strong></div>
          <div className="ledger-row"><span>Claims with evidence</span><strong>{job.quality.claims_with_evidence}</strong></div>
          <div className="ledger-row"><span>Validation errors</span><strong>{job.quality.validation_errors}</strong></div>
        </div>
        <div className="card review-card">
          <div className="section-heading"><div><p className="eyebrow">04 · HUMAN REVIEW</p><h2>Risk queue</h2></div><span className="review-count">{reviews.length} OPEN</span></div>
          {reviews.length === 0 ? <div className="empty-state">No open review task is loaded for this tenant.</div> : reviews.slice(0, 8).map((task) => <article className="review-task" key={task.id}><div><strong>{task.product_id}</strong><small>Risk {Math.round(task.risk * 100)}% · {task.payload.manufacturer ?? "manufacturer unresolved"}</small></div><div className="review-buttons"><button onClick={() => decide(task.id, "approved")}>Approve</button><button onClick={() => decide(task.id, "rejected")}>Reject</button></div></article>)}
        </div>
      </section>}

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
