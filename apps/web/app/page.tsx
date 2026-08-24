"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { LucideIcon } from "lucide-react";
import {
  AlertCircle,
  AlertTriangle,
  ArrowDownCircle,
  BarChart3,
  CheckCircle2,
  ChevronRight,
  CircleDashed,
  Clock,
  Download,
  FileSpreadsheet,
  FileText,
  Filter,
  Flame,
  GitBranch,
  Globe,
  Loader2,
  Package,
  RefreshCw,
  Shield,
  ShieldCheck,
  Sparkles,
  ThumbsDown,
  ThumbsUp,
  Upload,
  XCircle,
  Zap,
} from "lucide-react";

// ─── Config ────────────────────────────────────────────────────────────────
const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL || "https://forgegraph-api-root.vercel.app";
const TENANT_ID = "local";
const POLL_INTERVAL = 2000;
const MAX_POLLS = 90;
const TERMINAL_STATUSES = new Set([
  "completed",
  "waiting_review",
  "failed",
  "cancelled",
]);

// ─── Types ──────────────────────────────────────────────────────────────────
interface QualitySummary {
  total_rows: number;
  processed_rows: number;
  accepted_rows: number;
  review_rows: number;
  failed_rows: number;
  claims_total: number;
  claims_with_evidence: number;
  validation_errors: number;
  evidence_coverage: number;
}

interface JobResponse {
  id: string;
  status: string;
  filename: string;
  input_sha256: string;
  reference_pack_version: string;
  quality: QualitySummary;
  error?: string;
}

interface ReviewTask {
  id: string;
  job_id: string;
  product_id: string;
  risk: number;
  status: string;
  payload: Record<string, unknown>;
  assigned_to?: string;
  decision?: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

// ─── Helpers ────────────────────────────────────────────────────────────────
function apiHeaders() {
  return { "X-Tenant-ID": TENANT_ID };
}

function statusColor(status: string): string {
  switch (status) {
    case "ready":
    case "completed":
    case "approved":
      return "text-emerald-600";
    case "review_required":
    case "waiting_review":
      return "text-amber-600";
    case "blocked":
    case "failed":
    case "rejected":
      return "text-red-600";
    case "running":
      return "text-blue-600";
    default:
      return "text-slate-500";
  }
}

function statusBadge(status: string) {
  const variants: Record<string, string> = {
    ready: "badge-ready",
    completed: "badge-ready",
    approved: "badge-ready",
    review_required: "badge-review",
    waiting_review: "badge-review",
    blocked: "badge-blocked",
    failed: "badge-blocked",
    rejected: "badge-blocked",
    running: "badge-running",
  };
  return variants[status] || "badge-neutral";
}

function riskColor(risk: number): string {
  if (risk >= 0.7) return "risk-high";
  if (risk >= 0.4) return "risk-medium";
  return "risk-low";
}

function pct(n: number, total: number) {
  return total === 0 ? 0 : Math.round((n / total) * 100);
}

// ─── Pipeline Stage Indicator ────────────────────────────────────────────────
const STAGES = [
  { id: 1, label: "Ingest", icon: Upload },
  { id: 2, label: "Normalize", icon: RefreshCw },
  { id: 3, label: "Classify", icon: GitBranch },
  { id: 4, label: "Evidence", icon: Globe },
  { id: 5, label: "Extract", icon: Sparkles },
  { id: 6, label: "Validate", icon: Shield },
  { id: 7, label: "Publish", icon: CheckCircle2 },
];

function PipelineIndicator({ status }: { status: string | null }) {
  const active =
    status === "running" ? 5 : TERMINAL_STATUSES.has(status || "") ? 7 : 0;
  return (
    <div className="flex items-center gap-1 overflow-x-auto scrollbar-thin pb-1">
      {STAGES.map((stage, idx) => {
        const done = active >= stage.id;
        const current = status === "running" && stage.id === active;
        const Icon = stage.icon;
        return (
          <div key={stage.id} className="flex items-center gap-1 flex-shrink-0">
            <div
              className={`flex flex-col items-center gap-1 px-3 py-2 rounded-lg transition-all duration-300 ${
                done
                  ? "bg-navy-900 text-white"
                  : current
                  ? "bg-cyan-forge/20 text-navy-900 border border-cyan-forge animate-pulse"
                  : "bg-slate-100 text-slate-400"
              }`}
            >
              <Icon size={14} />
              <span className="text-[10px] font-semibold whitespace-nowrap">
                {stage.label}
              </span>
            </div>
            {idx < STAGES.length - 1 && (
              <ChevronRight
                size={12}
                className={done ? "text-navy-900" : "text-slate-300"}
              />
            )}
          </div>
        );
      })}
    </div>
  );
}

// ─── Metric Card ─────────────────────────────────────────────────────────────
function MetricCard({
  label,
  value,
  sub,
  color = "text-navy-900",
  icon: Icon,
}: {
  label: string;
  value: string | number;
  sub?: string;
  color?: string;
  icon?: LucideIcon;
}) {
  return (
    <div className="bg-white rounded-xl border border-slate-200 p-4 flex flex-col gap-2 shadow-sm hover:shadow-md transition-shadow duration-200">
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider">
          {label}
        </span>
        {Icon && <Icon size={16} className="text-slate-400" />}
      </div>
      <div className={`text-3xl font-black tracking-tight ${color}`}>{value}</div>
      {sub && <div className="text-xs text-slate-400">{sub}</div>}
    </div>
  );
}

// ─── Progress Bar ─────────────────────────────────────────────────────────────
function ProgressBar({
  pct: percent,
  color = "bg-navy-900",
  label,
}: {
  pct: number;
  color?: string;
  label?: string;
}) {
  return (
    <div className="space-y-1">
      {label && (
        <div className="flex justify-between text-xs text-slate-500">
          <span>{label}</span>
          <span className="font-bold">{percent}%</span>
        </div>
      )}
      <div className="progress-bar">
        <div
          className={`progress-fill ${color}`}
          style={{ width: `${Math.min(100, percent)}%` }}
        />
      </div>
    </div>
  );
}

// ─── Review Task Card ─────────────────────────────────────────────────────────
function ReviewTaskCard({
  task,
  onDecide,
}: {
  task: ReviewTask;
  onDecide: (taskId: string, decision: string) => void;
}) {
  const risk = task.risk;
  const isOpen = task.status === "open";
  const payload = task.payload as {
    mpn?: string;
    manufacturer?: string;
    brand?: string;
    category?: string;
    publish_status?: string;
    validations?: Array<{ rule_id: string; severity: string; message: string }>;
  };

  return (
    <div
      className={`bg-white border rounded-xl p-4 transition-all duration-200 hover:shadow-md ${
        !isOpen ? "opacity-60 border-slate-200" : "border-slate-200 hover:border-slate-300"
      }`}
    >
      {/* Header */}
      <div className="flex items-start justify-between gap-3 mb-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap mb-1">
            <span className="font-mono text-sm font-bold text-navy-900 truncate">
              {task.product_id}
            </span>
            <span className={statusBadge(task.status)}>{task.status}</span>
          </div>
          {payload.manufacturer && (
            <p className="text-xs text-slate-500 truncate">
              {payload.manufacturer}
              {payload.brand ? ` · ${payload.brand}` : ""}
              {payload.category ? ` · ${payload.category}` : ""}
            </p>
          )}
        </div>
        {/* Risk meter */}
        <div className="flex-shrink-0 text-right">
          <div className="text-xs text-slate-400 mb-1">Risk</div>
          <div
            className={`text-sm font-black ${
              risk >= 0.7
                ? "text-red-600"
                : risk >= 0.4
                ? "text-amber-600"
                : "text-emerald-600"
            }`}
          >
            {Math.round(risk * 100)}%
          </div>
          <div className="w-12 h-1.5 rounded-full bg-slate-100 mt-1">
            <div
              className={`h-full rounded-full ${riskColor(risk)}`}
              style={{ width: `${risk * 100}%` }}
            />
          </div>
        </div>
      </div>

      {/* Validation issues */}
      {payload.validations && payload.validations.length > 0 && (
        <div className="mb-3 space-y-1">
          {payload.validations.slice(0, 2).map((v, i) => (
            <div
              key={i}
              className={`flex items-start gap-1.5 text-xs rounded-lg px-2 py-1.5 ${
                v.severity === "error"
                  ? "bg-red-50 text-red-700"
                  : "bg-amber-50 text-amber-700"
              }`}
            >
              {v.severity === "error" ? (
                <AlertCircle size={12} className="flex-shrink-0 mt-0.5" />
              ) : (
                <AlertTriangle size={12} className="flex-shrink-0 mt-0.5" />
              )}
              <span className="leading-tight">{v.message}</span>
            </div>
          ))}
          {payload.validations.length > 2 && (
            <p className="text-xs text-slate-400 pl-2">
              +{payload.validations.length - 2} more issues
            </p>
          )}
        </div>
      )}

      {/* Decision buttons */}
      {isOpen && (
        <div className="flex items-center gap-2 mt-2 pt-3 border-t border-slate-100">
          <button
            id={`approve-${task.id}`}
            onClick={() => onDecide(task.id, "approved")}
            className="flex-1 flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg bg-emerald-50 text-emerald-700 border border-emerald-200 text-xs font-bold hover:bg-emerald-100 transition-colors duration-150 focus:outline-none focus:ring-2 focus:ring-emerald-500 focus:ring-offset-1"
          >
            <ThumbsUp size={13} />
            Approve
          </button>
          <button
            id={`reject-${task.id}`}
            onClick={() => onDecide(task.id, "rejected")}
            className="flex-1 flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg bg-red-50 text-red-700 border border-red-200 text-xs font-bold hover:bg-red-100 transition-colors duration-150 focus:outline-none focus:ring-2 focus:ring-red-500 focus:ring-offset-1"
          >
            <ThumbsDown size={13} />
            Reject
          </button>
        </div>
      )}
      {!isOpen && task.decision && (
        <div className="mt-2 pt-3 border-t border-slate-100">
          <p className="text-xs text-slate-400">
            Decided by{" "}
            <span className="font-semibold">
              {String(task.decision.actor || "system")}
            </span>{" "}
            ·{" "}
            <span className={statusColor(task.status)}>
              {task.status.toUpperCase()}
            </span>
          </p>
        </div>
      )}
    </div>
  );
}

// ─── Main Page ─────────────────────────────────────────────────────────────────
export default function Home() {
  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [message, setMessage] = useState("");
  const [job, setJob] = useState<JobResponse | null>(null);
  const [reviews, setReviews] = useState<ReviewTask[]>([]);
  const [reviewFilter, setReviewFilter] = useState<string>("open");
  const [decidingId, setDecidingId] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<"quality" | "review" | "audit">("quality");
  const inputRef = useRef<HTMLInputElement>(null);
  const pollsRef = useRef(0);
  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // ── Poll job ────────────────────────────────────────────────────────────
  const pollJob = useCallback(async (jobId: string) => {
    if (pollsRef.current >= MAX_POLLS) {
      setMessage("⚠️ Processing timed out. Please refresh.");
      return;
    }
    pollsRef.current++;
    try {
      const res = await fetch(`${API_BASE}/api/v1/catalog/jobs/${jobId}`, {
        headers: apiHeaders(),
      });
      if (!res.ok) return;
      const updated: JobResponse = await res.json();
      setJob(updated);
      if (!TERMINAL_STATUSES.has(updated.status)) {
        pollRef.current = setTimeout(() => pollJob(jobId), POLL_INTERVAL);
      } else {
        setUploading(false);
        setMessage(
          updated.status === "failed"
            ? `❌ Processing failed: ${updated.error || "Unknown error"}`
            : `✅ Processing complete — ${updated.quality.processed_rows} rows processed`
        );
        // Fetch review tasks
        fetchReviews(jobId);
      }
    } catch {
      pollRef.current = setTimeout(() => pollJob(jobId), POLL_INTERVAL);
    }
  }, []);

  const fetchReviews = useCallback(async (jobId?: string) => {
    try {
      const url = new URL(`${API_BASE}/api/v1/reviews`);
      if (reviewFilter) url.searchParams.set("status", reviewFilter);
      const res = await fetch(url.toString(), { headers: apiHeaders() });
      if (!res.ok) return;
      const all: ReviewTask[] = await res.json();
      const filtered = jobId
        ? all.filter((t) => t.job_id === jobId)
        : all;
      setReviews(filtered.sort((a, b) => b.risk - a.risk));
    } catch {
      // ignore
    }
  }, [reviewFilter]);

  useEffect(() => {
    if (job?.id) fetchReviews(job.id);
  }, [reviewFilter, job?.id, fetchReviews]);

  // Cleanup poll on unmount
  useEffect(() => {
    return () => {
      if (pollRef.current) clearTimeout(pollRef.current);
    };
  }, []);

  // ── Upload ──────────────────────────────────────────────────────────────
  const handleUpload = async () => {
    if (!file) return;
    if (pollRef.current) clearTimeout(pollRef.current);
    pollsRef.current = 0;
    setUploading(true);
    setMessage("Uploading and starting pipeline…");
    setJob(null);
    setReviews([]);
    const form = new FormData();
    form.append("file", file);
    try {
      const res = await fetch(
        `${API_BASE}/api/v1/catalog/jobs?reference_pack_version=starter-v0`,
        { method: "POST", headers: apiHeaders(), body: form }
      );
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "Upload failed" }));
        setMessage(`❌ ${err.detail || "Upload failed"}`);
        setUploading(false);
        return;
      }
      const newJob: JobResponse = await res.json();
      setJob(newJob);
      setActiveTab("quality");
      if (!TERMINAL_STATUSES.has(newJob.status)) {
        setMessage("⏳ Processing — Stage 1: Ingesting file…");
        pollRef.current = setTimeout(() => pollJob(newJob.id), POLL_INTERVAL);
      } else {
        setUploading(false);
        setMessage(`✅ Complete — ${newJob.quality.processed_rows} rows processed`);
        fetchReviews(newJob.id);
      }
    } catch {
      setMessage("❌ Network error. Please check your connection.");
      setUploading(false);
    }
  };

  // ── Review decision ──────────────────────────────────────────────────────
  const handleDecide = async (taskId: string, decision: string) => {
    setDecidingId(taskId);
    try {
      const res = await fetch(`${API_BASE}/api/v1/reviews/${taskId}/decision`, {
        method: "POST",
        headers: { ...apiHeaders(), "Content-Type": "application/json" },
        body: JSON.stringify({ decision }),
      });
      if (!res.ok) return;
      // Refresh reviews + job
      if (job) {
        const jobRes = await fetch(`${API_BASE}/api/v1/catalog/jobs/${job.id}`, {
          headers: apiHeaders(),
        });
        if (jobRes.ok) setJob(await jobRes.json());
        fetchReviews(job.id);
      }
    } catch {
      // ignore
    } finally {
      setDecidingId(null);
    }
  };

  // ── Drag & drop ──────────────────────────────────────────────────────────
  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragging(false);
    const dropped = e.dataTransfer.files[0];
    if (dropped) setFile(dropped);
  };

  const q = job?.quality;

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 via-white to-blue-50/30">
      {/* ── Topbar ─────────────────────────────────────────────────────────── */}
      <header className="sticky top-0 z-50 bg-white/80 backdrop-blur-xl border-b border-slate-200/60 shadow-sm">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex items-center justify-between h-16">
            {/* Brand */}
            <div className="flex items-center gap-3">
              <div className="w-9 h-9 bg-navy-900 rounded-lg flex items-center justify-center shadow-md">
                <span className="text-cyan-forge font-black text-lg leading-none">F</span>
              </div>
              <div>
                <span className="text-navy-900 font-black text-xl tracking-tight">
                  ForgeGraph
                </span>
                <div className="text-[10px] text-slate-400 font-medium tracking-widest uppercase -mt-0.5">
                  Industrial Intelligence
                </div>
              </div>
            </div>
            {/* Status pills */}
            <div className="flex items-center gap-3">
              {job && (
                <span className={statusBadge(job.status)}>{job.status}</span>
              )}
              <div className="hidden sm:flex items-center gap-1.5 bg-emerald-50 border border-emerald-200 rounded-full px-3 py-1">
                <div className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
                <span className="text-xs font-bold text-emerald-700 uppercase tracking-wide">
                  Live
                </span>
              </div>
            </div>
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-8">
        {/* ── Hero ──────────────────────────────────────────────────────────── */}
        <section className="flex flex-col lg:flex-row gap-8 items-start">
          <div className="flex-1">
            <p className="text-xs font-bold text-blue-600 uppercase tracking-widest mb-3">
              UniHack 2026 · AI-Powered Product Intelligence
            </p>
            <h1 className="text-4xl sm:text-5xl lg:text-6xl font-black text-navy-900 leading-none tracking-tight mb-4">
              The model proposes.
              <br />
              <span className="gradient-text">The firewall decides.</span>
            </h1>
            <p className="text-slate-500 text-lg leading-relaxed max-w-xl">
              ForgeGraph converts sparse supplier spreadsheets into governed,
              evidence-backed, publication-ready product intelligence through 7
              deterministic pipeline stages.
            </p>
          </div>
          {/* Pipeline stages */}
          <div className="w-full lg:w-auto flex-shrink-0 bg-white rounded-2xl border border-slate-200 shadow-sm p-4">
            <p className="text-xs font-bold text-slate-400 uppercase tracking-widest mb-3">
              7-Stage Pipeline
            </p>
            <PipelineIndicator status={job?.status || null} />
          </div>
        </section>

        {/* ── Workspace ──────────────────────────────────────────────────────── */}
        <section className="grid grid-cols-1 lg:grid-cols-5 gap-6">
          {/* Upload card */}
          <div className="lg:col-span-2 bg-white rounded-2xl border border-slate-200 shadow-sm p-6">
            <div className="flex items-center gap-2 mb-1">
              <span className="w-6 h-6 rounded-full bg-navy-900 text-white text-xs font-black flex items-center justify-center">
                1
              </span>
              <h2 className="text-lg font-black text-navy-900">Ingest</h2>
            </div>
            <p className="text-sm text-slate-400 mb-4">
              Upload a supplier CSV or XLSX file to begin the pipeline.
            </p>

            {/* Drop zone */}
            <div
              id="upload-dropzone"
              onDragOver={(e) => {
                e.preventDefault();
                setDragging(true);
              }}
              onDragLeave={() => setDragging(false)}
              onDrop={onDrop}
              onClick={() => inputRef.current?.click()}
              className={`border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-all duration-200 min-h-[160px] flex flex-col items-center justify-center gap-3 ${
                dragging
                  ? "border-cyan-forge bg-cyan-forge/5 scale-[1.01]"
                  : file
                  ? "border-emerald-400 bg-emerald-50"
                  : "border-slate-300 hover:border-slate-400 bg-slate-50 hover:bg-white"
              }`}
            >
              <input
                id="file-input"
                ref={inputRef}
                type="file"
                accept=".csv,.xlsx"
                className="hidden"
                onChange={(e) => e.target.files?.[0] && setFile(e.target.files[0])}
              />
              {file ? (
                <>
                  <div className="w-10 h-10 bg-emerald-100 rounded-xl flex items-center justify-center">
                    <FileSpreadsheet size={20} className="text-emerald-600" />
                  </div>
                  <div>
                    <p className="text-sm font-bold text-emerald-700 truncate max-w-[200px]">
                      {file.name}
                    </p>
                    <p className="text-xs text-slate-400 mt-0.5">
                      {(file.size / 1024).toFixed(1)} KB
                    </p>
                  </div>
                  <p className="text-xs text-slate-400">Click to change</p>
                </>
              ) : (
                <>
                  <div className="w-12 h-12 bg-navy-900 rounded-xl flex items-center justify-center">
                    <Upload size={22} className="text-cyan-forge" />
                  </div>
                  <div>
                    <p className="text-sm font-semibold text-slate-600">
                      Drop a file or click to browse
                    </p>
                    <p className="text-xs text-slate-400 mt-1">
                      CSV or XLSX · Max 25 MB
                    </p>
                  </div>
                </>
              )}
            </div>

            {/* Submit */}
            <button
              id="start-pipeline-btn"
              onClick={handleUpload}
              disabled={!file || uploading}
              className="mt-4 w-full flex items-center justify-center gap-2 px-4 py-3 rounded-xl bg-navy-900 text-white font-bold text-sm hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-all duration-200 focus:outline-none focus:ring-2 focus:ring-navy-500 focus:ring-offset-2"
            >
              {uploading ? (
                <>
                  <Loader2 size={16} className="animate-spin" />
                  Processing…
                </>
              ) : (
                <>
                  <Zap size={16} />
                  Start Pipeline
                </>
              )}
            </button>

            {/* Message */}
            {message && (
              <div
                className={`mt-3 px-3 py-2.5 rounded-lg text-sm leading-snug ${
                  message.startsWith("❌")
                    ? "bg-red-50 text-red-700 border border-red-200"
                    : message.startsWith("✅")
                    ? "bg-emerald-50 text-emerald-700 border border-emerald-200"
                    : "bg-blue-50 text-blue-700 border border-blue-200"
                }`}
              >
                {message}
              </div>
            )}
          </div>

          {/* Results panel */}
          <div className="lg:col-span-3 bg-white rounded-2xl border border-slate-200 shadow-sm">
            {/* Tab bar */}
            <div className="flex border-b border-slate-200">
              {(
                [
                  { id: "quality", label: "Quality Dashboard", icon: BarChart3 },
                  { id: "review", label: "Review Queue", icon: Shield, badge: reviews.filter((r) => r.status === "open").length },
                  { id: "audit", label: "Export", icon: Download },
                ] as const
              ).map((tab) => (
                <button
                  key={tab.id}
                  id={`tab-${tab.id}`}
                  onClick={() => setActiveTab(tab.id)}
                  className={`flex items-center gap-2 px-4 py-3.5 text-sm font-semibold transition-colors duration-150 border-b-2 focus:outline-none ${
                    activeTab === tab.id
                      ? "text-navy-900 border-navy-900"
                      : "text-slate-400 border-transparent hover:text-slate-600"
                  }`}
                >
                  <tab.icon size={14} />
                  <span className="hidden sm:inline">{tab.label}</span>
                  {"badge" in tab && tab.badge > 0 && (
                    <span className="bg-amber-100 text-amber-700 text-xs font-bold px-1.5 py-0.5 rounded-full">
                      {tab.badge}
                    </span>
                  )}
                </button>
              ))}
            </div>

            <div className="p-6">
              {/* ── Quality Dashboard ──────────────────────────────────────── */}
              {activeTab === "quality" && (
                <div className="animate-fade-in">
                  <div className="flex items-center gap-2 mb-4">
                    <span className="w-6 h-6 rounded-full bg-navy-900 text-white text-xs font-black flex items-center justify-center">2</span>
                    <h2 className="text-lg font-black text-navy-900">Quality Trust Dashboard</h2>
                    {uploading && <Loader2 size={16} className="text-blue-500 animate-spin ml-auto" />}
                  </div>

                  {!q ? (
                    <div className="flex flex-col items-center justify-center py-16 text-center">
                      <div className="w-16 h-16 bg-slate-100 rounded-2xl flex items-center justify-center mb-4">
                        <Package size={28} className="text-slate-300" />
                      </div>
                      <p className="text-slate-400 font-medium">
                        Upload a file to see the quality dashboard
                      </p>
                      <p className="text-slate-300 text-sm mt-1">
                        All 7 pipeline stages will run automatically
                      </p>
                    </div>
                  ) : (
                    <div className="space-y-5">
                      {/* Core metrics */}
                      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                        <MetricCard
                          label="Rows Processed"
                          value={q.processed_rows.toLocaleString()}
                          sub={`of ${q.total_rows.toLocaleString()}`}
                          color="text-navy-900"
                          icon={FileText}
                        />
                        <MetricCard
                          label="Ready to Publish"
                          value={`${pct(q.accepted_rows, q.total_rows)}%`}
                          sub={`${q.accepted_rows} rows`}
                          color="text-emerald-600"
                          icon={CheckCircle2}
                        />
                        <MetricCard
                          label="Needs Review"
                          value={`${pct(q.review_rows, q.total_rows)}%`}
                          sub={`${q.review_rows} rows`}
                          color="text-amber-600"
                          icon={AlertTriangle}
                        />
                        <MetricCard
                          label="Evidence Coverage"
                          value={`${Math.round(q.evidence_coverage * 100)}%`}
                          sub={`${q.claims_with_evidence} / ${q.claims_total} claims`}
                          color={q.evidence_coverage > 0.5 ? "text-emerald-600" : "text-amber-600"}
                          icon={ShieldCheck}
                        />
                      </div>

                      {/* Progress bars */}
                      <div className="bg-slate-50 rounded-xl p-4 space-y-3">
                        <h3 className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-3">
                          Publication Pipeline
                        </h3>
                        <ProgressBar
                          pct={pct(q.accepted_rows, q.total_rows)}
                          color="bg-emerald-500"
                          label="Ready to publish"
                        />
                        <ProgressBar
                          pct={pct(q.review_rows, q.total_rows)}
                          color="bg-amber-400"
                          label="Awaiting human review"
                        />
                        <ProgressBar
                          pct={pct(q.failed_rows, q.total_rows)}
                          color="bg-red-400"
                          label="Blocked (errors)"
                        />
                        <ProgressBar
                          pct={Math.round(q.evidence_coverage * 100)}
                          color="bg-blue-500"
                          label="Evidence coverage"
                        />
                      </div>

                      {/* Claim + validation stats */}
                      <div className="grid grid-cols-3 gap-3">
                        <div className="bg-navy-900 rounded-xl p-4 text-white">
                          <p className="text-xs text-slate-400 mb-1">Claims Total</p>
                          <p className="text-2xl font-black">{q.claims_total.toLocaleString()}</p>
                        </div>
                        <div className="bg-slate-800 rounded-xl p-4 text-white">
                          <p className="text-xs text-slate-400 mb-1">With Evidence</p>
                          <p className="text-2xl font-black text-cyan-forge">
                            {q.claims_with_evidence.toLocaleString()}
                          </p>
                        </div>
                        <div className="bg-red-900/80 rounded-xl p-4 text-white">
                          <p className="text-xs text-red-300 mb-1">Validation Errors</p>
                          <p className="text-2xl font-black">
                            {q.validation_errors.toLocaleString()}
                          </p>
                        </div>
                      </div>

                      {/* Claim ledger metadata */}
                      {job && (
                        <div className="border border-slate-200 rounded-xl divide-y divide-slate-100">
                          <div className="px-4 py-3 flex justify-between items-center">
                            <span className="text-xs text-slate-400 font-medium">Job ID</span>
                            <span className="font-mono text-xs text-navy-900 truncate max-w-[200px]">
                              {job.id}
                            </span>
                          </div>
                          <div className="px-4 py-3 flex justify-between items-center">
                            <span className="text-xs text-slate-400 font-medium">SHA-256</span>
                            <span className="font-mono text-xs text-navy-900 truncate max-w-[200px]">
                              {job.input_sha256.slice(0, 24)}…
                            </span>
                          </div>
                          <div className="px-4 py-3 flex justify-between items-center">
                            <span className="text-xs text-slate-400 font-medium">Reference Pack</span>
                            <span className="badge-neutral">{job.reference_pack_version}</span>
                          </div>
                          <div className="px-4 py-3 flex justify-between items-center">
                            <span className="text-xs text-slate-400 font-medium">Status</span>
                            <span className={statusBadge(job.status)}>{job.status}</span>
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )}

              {/* ── Review Queue ─────────────────────────────────────────────── */}
              {activeTab === "review" && (
                <div className="animate-fade-in">
                  <div className="flex items-center justify-between gap-3 mb-4">
                    <div className="flex items-center gap-2">
                      <span className="w-6 h-6 rounded-full bg-navy-900 text-white text-xs font-black flex items-center justify-center">3</span>
                      <h2 className="text-lg font-black text-navy-900">Human Review</h2>
                    </div>
                    <div className="flex items-center gap-2">
                      <Filter size={13} className="text-slate-400" />
                      <select
                        id="review-filter"
                        value={reviewFilter}
                        onChange={(e) => setReviewFilter(e.target.value)}
                        className="text-xs border border-slate-200 rounded-lg px-2 py-1.5 text-slate-600 focus:outline-none focus:ring-2 focus:ring-navy-500 bg-white"
                      >
                        <option value="">All</option>
                        <option value="open">Open</option>
                        <option value="approved">Approved</option>
                        <option value="rejected">Rejected</option>
                      </select>
                      <button
                        id="refresh-reviews-btn"
                        onClick={() => job && fetchReviews(job.id)}
                        className="p-1.5 rounded-lg border border-slate-200 text-slate-400 hover:text-navy-900 hover:border-slate-300 transition-colors"
                      >
                        <RefreshCw size={13} />
                      </button>
                    </div>
                  </div>

                  {reviews.length === 0 ? (
                    <div className="flex flex-col items-center justify-center py-16 text-center">
                      <div className="w-16 h-16 bg-slate-100 rounded-2xl flex items-center justify-center mb-4">
                        <Shield size={28} className="text-slate-300" />
                      </div>
                      <p className="text-slate-400 font-medium">
                        {job ? "No review tasks found" : "Upload a file to see review tasks"}
                      </p>
                      <p className="text-slate-300 text-sm mt-1">
                        The QualityFirewall routes uncertain products here
                      </p>
                    </div>
                  ) : (
                    <div className="space-y-3 max-h-[500px] overflow-y-auto scrollbar-thin pr-1">
                      {decidingId && (
                        <div className="flex items-center gap-2 text-sm text-blue-600 bg-blue-50 rounded-lg px-3 py-2">
                          <Loader2 size={14} className="animate-spin" />
                          Recording decision…
                        </div>
                      )}
                      {reviews.map((task) => (
                        <ReviewTaskCard
                          key={task.id}
                          task={task}
                          onDecide={handleDecide}
                        />
                      ))}
                    </div>
                  )}
                </div>
              )}

              {/* ── Export / Audit ────────────────────────────────────────────── */}
              {activeTab === "audit" && (
                <div className="animate-fade-in">
                  <div className="flex items-center gap-2 mb-4">
                    <span className="w-6 h-6 rounded-full bg-navy-900 text-white text-xs font-black flex items-center justify-center">4</span>
                    <h2 className="text-lg font-black text-navy-900">Export Center</h2>
                  </div>

                  {!job ? (
                    <div className="flex flex-col items-center justify-center py-16 text-center">
                      <div className="w-16 h-16 bg-slate-100 rounded-2xl flex items-center justify-center mb-4">
                        <Download size={28} className="text-slate-300" />
                      </div>
                      <p className="text-slate-400 font-medium">
                        No job available for export
                      </p>
                    </div>
                  ) : (
                    <div className="space-y-4">
                      <div className="bg-navy-900 rounded-xl p-5 text-white">
                        <div className="flex items-center gap-2 mb-3">
                          <ShieldCheck size={16} className="text-cyan-forge" />
                          <span className="text-sm font-bold">Governed Export</span>
                        </div>
                        <p className="text-xs text-slate-300 leading-relaxed">
                          Output is schema-aware and tied to reference pack{" "}
                          <span className="font-mono text-cyan-forge">
                            {job.reference_pack_version}
                          </span>
                          . Every exported row preserves claim provenance.
                        </p>
                      </div>

                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                        <a
                          id="export-csv-link"
                          href={`${API_BASE}/api/v1/catalog/jobs/${job.id}/export.csv`}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="flex items-center gap-3 p-4 border border-slate-200 rounded-xl hover:border-navy-900 hover:bg-slate-50 transition-all duration-150 group"
                        >
                          <div className="w-10 h-10 bg-emerald-100 rounded-lg flex items-center justify-center group-hover:bg-emerald-200 transition-colors">
                            <FileText size={20} className="text-emerald-600" />
                          </div>
                          <div>
                            <p className="text-sm font-bold text-navy-900">Download CSV</p>
                            <p className="text-xs text-slate-400">Comma-separated values</p>
                          </div>
                          <ArrowDownCircle size={16} className="text-slate-300 ml-auto group-hover:text-navy-900 transition-colors" />
                        </a>

                        <a
                          id="export-xlsx-link"
                          href={`${API_BASE}/api/v1/catalog/jobs/${job.id}/export.xlsx`}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="flex items-center gap-3 p-4 border border-slate-200 rounded-xl hover:border-navy-900 hover:bg-slate-50 transition-all duration-150 group"
                        >
                          <div className="w-10 h-10 bg-blue-100 rounded-lg flex items-center justify-center group-hover:bg-blue-200 transition-colors">
                            <FileSpreadsheet size={20} className="text-blue-600" />
                          </div>
                          <div>
                            <p className="text-sm font-bold text-navy-900">Download XLSX</p>
                            <p className="text-xs text-slate-400">Excel workbook</p>
                          </div>
                          <ArrowDownCircle size={16} className="text-slate-300 ml-auto group-hover:text-navy-900 transition-colors" />
                        </a>
                      </div>

                      {/* Quality summary for export */}
                      {q && (
                        <div className="bg-slate-50 rounded-xl p-4 border border-slate-200">
                          <p className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-3">
                            Export Summary
                          </p>
                          <div className="grid grid-cols-2 gap-3 text-sm">
                            <div className="flex justify-between">
                              <span className="text-slate-500">Total rows</span>
                              <span className="font-bold text-navy-900">{q.total_rows}</span>
                            </div>
                            <div className="flex justify-between">
                              <span className="text-slate-500">Ready rows</span>
                              <span className="font-bold text-emerald-600">{q.accepted_rows}</span>
                            </div>
                            <div className="flex justify-between">
                              <span className="text-slate-500">Review rows</span>
                              <span className="font-bold text-amber-600">{q.review_rows}</span>
                            </div>
                            <div className="flex justify-between">
                              <span className="text-slate-500">Claims</span>
                              <span className="font-bold text-navy-900">{q.claims_total}</span>
                            </div>
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        </section>

        {/* ── Capabilities ───────────────────────────────────────────────────── */}
        <section>
          <h2 className="text-2xl font-black text-navy-900 mb-6">
            Why ForgeGraph stands out
          </h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {[
              {
                icon: Shield,
                title: "Deterministic Governance",
                desc: "LOV checks, UOM normalization, contradiction detection, and evidence-policy rules run before any value can be published.",
              },
              {
                icon: Flame,
                title: "Claim-Level Provenance",
                desc: "Every attribute is an atomic claim with confidence, source, evidence reference, rule version, and reviewer decision.",
              },
              {
                icon: GitBranch,
                title: "Versioned Reference Packs",
                desc: "Manufacturers, brands, LOVs, UOMs, taxonomy, and schemas are versioned governance data — not hardcoded logic.",
              },
              {
                icon: Sparkles,
                title: "Controlled AI Extraction",
                desc: "AI operates under strict schemas, allowed-value context, and an explicit abstention rule. Temperature=0.",
              },
              {
                icon: Globe,
                title: "SSRF-Safe Evidence Retrieval",
                desc: "Only approved manufacturer domains. Private IP rejection. Content-length limits. Sandbox-parsed documents.",
              },
              {
                icon: BarChart3,
                title: "Risk-Based Human Review",
                desc: "Risk = 0.25 + failures×0.1 + unresolved×0.1. Humans focus on ambiguity — not routine matches.",
              },
            ].map(({ icon: Icon, title, desc }) => (
              <div
                key={title}
                className="bg-navy-900 rounded-2xl p-5 text-white flex gap-4 hover:bg-navy-800 transition-colors duration-200"
              >
                <div className="w-1 flex-shrink-0 bg-cyan-forge rounded-full" />
                <div>
                  <div className="flex items-center gap-2 mb-2">
                    <Icon size={16} className="text-cyan-forge" />
                    <h3 className="text-sm font-bold">{title}</h3>
                  </div>
                  <p className="text-xs text-slate-300 leading-relaxed">{desc}</p>
                </div>
              </div>
            ))}
          </div>
        </section>
      </main>

      {/* ── Footer ─────────────────────────────────────────────────────────── */}
      <footer className="border-t border-slate-200 bg-white/50 mt-12">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6 flex flex-col sm:flex-row items-center justify-between gap-4">
          <div className="flex items-center gap-2">
            <div className="w-6 h-6 bg-navy-900 rounded flex items-center justify-center">
              <span className="text-cyan-forge font-black text-xs">F</span>
            </div>
            <span className="text-xs text-slate-400">
              ForgeGraph · Team Zen Z · UniHack 2026
            </span>
          </div>
          <div className="flex items-center gap-4 text-xs text-slate-400">
            <a
              href="https://forgegraph-api-root.vercel.app/docs"
              target="_blank"
              rel="noopener noreferrer"
              className="hover:text-navy-900 transition-colors"
            >
              API Docs
            </a>
            <a
              href="https://forgegraph-api-root.vercel.app/health/live"
              target="_blank"
              rel="noopener noreferrer"
              className="hover:text-navy-900 transition-colors"
            >
              Health
            </a>
            <a
              href="https://github.com/SriRamkunamsetty/ForgeGraph-UniHack-Hack2Skill"
              target="_blank"
              rel="noopener noreferrer"
              className="hover:text-navy-900 transition-colors"
            >
              GitHub
            </a>
          </div>
        </div>
      </footer>
    </div>
  );
}
