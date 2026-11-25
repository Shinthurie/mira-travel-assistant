"use client";
// Staff page (requirements 6, 7, 8). Login is checked by the backend on every request:
// travellers without a staff token get 401 and see nothing.
import { useCallback, useEffect, useState } from "react";

type Quote = {
  ref: string; tour_id: string; start_date: string; cost_usd: string; price_usd: string; gross_profit_usd: string;
  gross_profit_pct: string; deposit_usd: string; cost_lines: { label: string; currency: string; amount: string }[];
  settings_overridden: string[];
};
type Enquiry = {
  id: number; ref: string; kind: string; summary: string; tour_id: string | null; status: string; created_at: string;
  trace_id: string | null; trace_url: string | null; contact: Record<string, string | null>; quote: Quote | null;
  flags: { ref: string; reason: string; detail: string; severity: string }[];
  notes: { author: string; text: string; created_at: string }[];
};
type Flag = { ref: string; source: string; reason: string; detail: string; tour_id: string | null; severity: string; trace_url: string | null; created_at: string };
type Draft = { id: number; doc_id: string; title: string; status: string; command: string; markdown: string; sources: string[]; created_by: string; approved_by: string | null };
type Auth = { token: string; role: string; user: string };

const KIND_LABEL: Record<string, string> = {
  quote: "Quote", no_quote: "No price", custom: "Custom trip", booking: "Booking", question: "Question",
};
const when = (iso: string) => new Date(iso).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
const money = (v: string) => Number(v).toLocaleString("en-US", { maximumFractionDigits: 2 });

async function api<T>(path: string, token: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api/backend/${path}`, {
    ...init, headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}`, ...(init?.headers || {}) },
  });
  const data = await res.json();
  // The backend answers unexpected errors with a friendly { ok: false, message } body: treat it as an error.
  if (!res.ok || (data && data.ok === false)) throw new Error(data.detail || data.message || `HTTP ${res.status}`);
  return data as T;
}

function TraceLink({ url, id, token }: { url: string | null; id: string | null; token: string }) {
  const [trace, setTrace] = useState<unknown>(null);
  if (!url) return null;
  if (url.startsWith("http")) return <a className="link" href={url} target="_blank" rel="noreferrer">Open trace</a>;
  return (
    <>
      <button className="link" onClick={async () => setTrace(trace ? null : await api(`staff/traces/${id}`, token))}>
        {trace ? "Hide trace" : "View trace"}
      </button>
      {trace ? <pre>{JSON.stringify(trace, null, 2)}</pre> : null}
    </>
  );
}

function Login({ onLogin }: { onLogin: (a: Auth) => void }) {
  const [error, setError] = useState("");
  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const res = await fetch("/api/backend/staff/login", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: f.get("username"), password: f.get("password") }) });
    const data = await res.json();
    if (!res.ok) { setError(data.detail || "Login failed"); return; }
    onLogin({ token: data.token, role: data.role, user: data.username });
  }
  return (
    <main className="staff-shell">
      <form className="cc-card accent-sky login" onSubmit={submit}>
        <div className="cc-kicker">Ceylon Compass · Staff</div>
        <h1 className="cc-title">Log in</h1>
        <label className="field">Username<input name="username" required autoComplete="username" /></label>
        <label className="field">Password<input name="password" type="password" required autoComplete="current-password" /></label>
        {error && <div className="cc-notice" role="alert">{error}</div>}
        <button className="btn btn-primary btn-block" type="submit">Log in</button>
        <p className="cc-muted">Demo users: staff / staff-demo and approver / approver-demo (set in .env).</p>
      </form>
    </main>
  );
}

function EnquiryRow({ e, auth, reload }: { e: Enquiry; auth: Auth; reload: () => void }) {
  async function addNote(text: string) {
    await api(`staff/enquiries/${e.id}/notes`, auth.token, { method: "POST", body: JSON.stringify({ text }) }); reload();
  }
  async function setStatus(status: string) {
    await api(`staff/enquiries/${e.id}`, auth.token, { method: "PATCH", body: JSON.stringify({ status }) }); reload();
  }
  return (
    <div className="row">
      <div>
        <h4>{e.ref} <span className="pill">{KIND_LABEL[e.kind] || e.kind}</span></h4>
        <div>{e.summary}</div>
        <div className="meta">{when(e.created_at)}{e.contact?.name ? ` · ${e.contact.name}, ${e.contact.email}` : ""}</div>
        <TraceLink url={e.trace_url} id={e.trace_id} token={auth.token} />
      </div>
      <div>
        {e.quote ? (
          <>
            <dl className="money">
              <dt>Price</dt><dd>USD {money(e.quote.price_usd)}</dd>
              <dt>Cost</dt><dd>USD {money(e.quote.cost_usd)}</dd>
              <dt>Gross profit</dt><dd>USD {money(e.quote.gross_profit_usd)} ({e.quote.gross_profit_pct}%)</dd>
              <dt>Deposit</dt><dd>USD {money(e.quote.deposit_usd)}</dd>
            </dl>
            {e.quote.settings_overridden.length > 0 && <span className="pill warning">Settings overridden</span>}
            <details>
              <summary className="link">Cost lines</summary>
              <ul className="steps">{e.quote.cost_lines.map((l) => <li key={l.label}>{l.label}: {l.currency} {money(l.amount)}</li>)}</ul>
            </details>
          </>
        ) : <span className="meta">No quote</span>}
      </div>
      <div style={{ display: "grid", gap: 6, alignContent: "start" }}>
        {e.flags.length === 0 && <span className="meta">No flags</span>}
        {e.flags.map((f) => (
          <div key={f.ref}><span className={`pill ${f.severity}`}>{f.reason.replace(/_/g, " ")}</span>
            <div className="meta">{f.detail}</div></div>
        ))}
      </div>
      <div>
        <select aria-label="Follow-up status" value={e.status} onChange={(ev) => void setStatus(ev.target.value)}>
          {["new", "contacted", "won", "lost"].map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        {e.notes.map((n, i) => <div key={i} className="meta" style={{ marginTop: 6 }}><b>{n.author}</b>: {n.text}</div>)}
        <form className="note-form" onSubmit={(ev) => {
          ev.preventDefault();
          const input = ev.currentTarget.elements.namedItem("note") as HTMLInputElement;
          if (input.value.trim()) { void addNote(input.value.trim()); input.value = ""; }
        }}>
          <input name="note" placeholder="Add a note" aria-label="Add a note" />
          <button className="btn btn-small" type="submit">Add</button>
        </form>
      </div>
    </div>
  );
}

export default function StaffPage() {
  const [auth, setAuth] = useState<Auth | null>(null);
  const [tab, setTab] = useState<"enquiries" | "flags" | "content">("enquiries");
  const [enquiries, setEnquiries] = useState<Enquiry[]>([]);
  const [flags, setFlags] = useState<Flag[]>([]);
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    try { const saved = sessionStorage.getItem("mira_staff"); if (saved) setAuth(JSON.parse(saved)); } catch { /* private mode */ }
  }, []);

  const load = useCallback(async () => {
    if (!auth) return;
    try {
      const [e, f, d] = await Promise.all([
        api<Enquiry[]>("staff/enquiries", auth.token), api<Flag[]>("staff/flags", auth.token),
        api<Draft[]>("staff/content/drafts", auth.token)]);
      setEnquiries(e); setFlags(f); setDrafts(d);
    } catch (err) {
      setMessage(String(err)); try { sessionStorage.removeItem("mira_staff"); } catch { /* ignore */ } setAuth(null);
    }
  }, [auth]);
  useEffect(() => { void load(); }, [load]);

  if (!auth) {
    return <Login onLogin={(a) => { try { sessionStorage.setItem("mira_staff", JSON.stringify(a)); } catch { /* ignore */ } setAuth(a); }} />;
  }

  async function createDraft(command: string) {
    setBusy(true); setMessage("Writing a draft from our existing pages...");
    try {
      await api("staff/content/drafts", auth!.token, { method: "POST", body: JSON.stringify({ command }) });
      await load();
      setMessage("Draft created. It is not live until an approver publishes it.");
    } catch (e) { setMessage(String(e)); }
    setBusy(false);
  }
  async function publish(id: number) {
    try {
      await api(`staff/content/drafts/${id}/publish`, auth!.token, { method: "POST" });
      await load();
      setMessage("Published. Mira can now answer questions about it. It has no rates, so it gets no price.");
    } catch (e) { setMessage(String(e)); void load(); }
  }

  const openFlags = flags.filter((f) => f.severity !== "info").length;
  const newEnquiries = enquiries.filter((e) => e.status === "new").length;
  const awaiting = drafts.filter((d) => d.status === "draft").length;
  const quotes = enquiries.filter((e) => e.quote).length;

  return (
    <div className="staff-shell">
      <header className="staff-top">
        <a className="brand" href="/"><span>Ceylon Compass<small>Staff</small></span></a>
        <div className="staff-who">
          <span>{auth.user} · {auth.role}</span>
          <button className="link" onClick={() => void load()}>Refresh</button>
          <button className="link" onClick={() => { try { sessionStorage.removeItem("mira_staff"); } catch { /* ignore */ } setAuth(null); }}>Log out</button>
        </div>
      </header>
      <main className="staff">
        <section className="tiles" aria-label="Summary">
          <div className="tile"><b>{newEnquiries}</b><span>New enquiries</span></div>
          <div className="tile"><b>{quotes}</b><span>Quotes sent</span></div>
          <div className="tile"><b>{openFlags}</b><span>Flags to check</span></div>
          <div className="tile"><b>{awaiting}</b><span>Drafts awaiting approval</span></div>
        </section>

        <nav className="tabs" role="tablist">
          {([["enquiries", `Enquiries (${enquiries.length})`], ["flags", `Flags (${flags.length})`], ["content", `Content (${drafts.length})`]] as const).map(([key, label]) => (
            <button key={key} role="tab" aria-selected={tab === key} className="tab" onClick={() => setTab(key)}>{label}</button>
          ))}
        </nav>
        {message && <div className="cc-notice" role="status">{message}</div>}

        {tab === "enquiries" && (
          <section className="panel rows">
            <div className="row row-head"><span>Enquiry</span><span>Quote (internal)</span><span>Flags</span><span>Follow-up</span></div>
            {enquiries.length === 0 && <div className="empty">No enquiries yet. They appear here as soon as Mira quotes or hands over.</div>}
            {enquiries.map((e) => <EnquiryRow key={e.id} e={e} auth={auth} reload={() => void load()} />)}
          </section>
        )}

        {tab === "flags" && (
          <section className="panel rows">
            <div className="row row-head"><span>Flag</span><span>Reason</span><span>Detail</span><span>Trace</span></div>
            {flags.length === 0 && <div className="empty">No flags. Every price so far came straight from the rates.</div>}
            {flags.map((f) => (
              <div className="row" key={f.ref}>
                <div><h4>{f.ref}</h4><div className="meta">{f.source} · {f.tour_id || "no tour"} · {when(f.created_at)}</div></div>
                <div><span className={`pill ${f.severity}`}>{f.reason.replace(/_/g, " ")}</span></div>
                <div>{f.detail}</div>
                <div>{f.trace_url?.startsWith("http") ? <a className="link" href={f.trace_url} target="_blank" rel="noreferrer">Open trace</a>
                  : <span className="meta">{f.trace_url ? "Local trace (see the enquiry)" : "No trace"}</span>}</div>
              </div>
            ))}
          </section>
        )}

        {tab === "content" && (
          <section className="drafts">
            <form className="cc-card accent-leaf" onSubmit={(e) => { e.preventDefault(); const c = (e.currentTarget.elements.namedItem("command") as HTMLInputElement).value; void createDraft(c); }}>
              <div className="cc-kicker">Content agent</div>
              <h3 className="cc-title">Draft a new tour page</h3>
              <label className="field">What should it write?<input name="command" defaultValue="Add a 5-day Hill Country tour using the Ella photos" /></label>
              <button className="btn btn-primary" type="submit" disabled={busy}>{busy ? "Writing..." : "Create draft"}</button>
              <p className="cc-muted">Drafts use only our published pages. Travellers never see a draft. Only an approver can publish.</p>
            </form>
            <div style={{ display: "grid", gap: "var(--cc-space-3)" }}>
              {drafts.length === 0 && <div className="panel empty">No drafts yet.</div>}
              {drafts.map((d) => (
                <article key={d.id} className="cc-card accent-sky" style={{ maxWidth: "none", margin: 0 }}>
                  <div className="cc-kicker">{d.doc_id} · {d.status === "draft" ? "Draft" : d.status === "published" ? `Published by ${d.approved_by}` : "Rejected"}</div>
                  <h3 className="cc-title">{d.title}</h3>
                  <p className="cc-muted">Asked for: &ldquo;{d.command}&rdquo; by {d.created_by}. Sources: {d.sources.join(", ")}</p>
                  <details><summary className="link">Read the page</summary><pre>{d.markdown}</pre></details>
                  {d.status === "draft" && (auth.role === "approver"
                    ? <button className="btn btn-primary" onClick={() => void publish(d.id)}>Approve and publish</button>
                    : <p className="cc-muted">Waiting for an approver.</p>)}
                </article>
              ))}
            </div>
          </section>
        )}
      </main>
    </div>
  );
}
