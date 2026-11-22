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
  if (!url) return <span className="cc-muted">no trace</span>;
  if (url.startsWith("http")) return <a href={url} target="_blank" rel="noreferrer">Open trace</a>;
  return (
    <>
      <button className="btn-link" onClick={async () => setTrace(trace ? null : await api(`staff/traces/${id}`, token))}>
        {trace ? "Hide trace" : "View trace"}
      </button>
      {trace ? <pre>{JSON.stringify(trace, null, 2)}</pre> : null}
    </>
  );
}

function Login({ onLogin }: { onLogin: (t: string, role: string, user: string) => void }) {
  const [error, setError] = useState("");
  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const res = await fetch("/api/backend/staff/login", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: f.get("username"), password: f.get("password") }) });
    const data = await res.json();
    if (!res.ok) { setError(data.detail || "Login failed"); return; }
    onLogin(data.token, data.role, data.username);
  }
  return (
    <form className="cc-card accent-sky" onSubmit={submit}>
      <h1 className="cc-title">Staff login</h1>
      <label className="cc-field">Username<input name="username" required /></label>
      <label className="cc-field">Password<input name="password" type="password" required /></label>
      {error && <div className="cc-notice">{error}</div>}
      <button className="btn btn-primary" type="submit">Log in</button>
      <div className="cc-muted">Demo users: staff / staff-demo, approver / approver-demo (set in .env).</div>
    </form>
  );
}

export default function StaffPage() {
  const [auth, setAuth] = useState<{ token: string; role: string; user: string } | null>(null);
  const [tab, setTab] = useState<"enquiries" | "flags" | "content">("enquiries");
  const [enquiries, setEnquiries] = useState<Enquiry[]>([]);
  const [flags, setFlags] = useState<Flag[]>([]);
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [message, setMessage] = useState("");

  useEffect(() => {
    const saved = sessionStorage.getItem("mira_staff");
    if (saved) setAuth(JSON.parse(saved));
  }, []);

  const load = useCallback(async () => {
    if (!auth) return;
    try {
      setEnquiries(await api<Enquiry[]>("staff/enquiries", auth.token));
      setFlags(await api<Flag[]>("staff/flags", auth.token));
      setDrafts(await api<Draft[]>("staff/content/drafts", auth.token));
    } catch (e) {
      setMessage(String(e)); sessionStorage.removeItem("mira_staff"); setAuth(null);
    }
  }, [auth]);
  useEffect(() => { void load(); }, [load]);

  if (!auth) {
    return <main className="staff"><Login onLogin={(token, role, user) => {
      const a = { token, role, user }; sessionStorage.setItem("mira_staff", JSON.stringify(a)); setAuth(a);
    }} />{message && <div className="cc-notice">{message}</div>}</main>;
  }

  async function addNote(id: number, text: string) {
    await api(`staff/enquiries/${id}/notes`, auth!.token, { method: "POST", body: JSON.stringify({ text }) }); void load();
  }
  async function setStatus(id: number, status: string) {
    await api(`staff/enquiries/${id}`, auth!.token, { method: "PATCH", body: JSON.stringify({ status }) }); void load();
  }
  async function createDraft(command: string) {
    setMessage("Creating draft...");
    await api("staff/content/drafts", auth!.token, { method: "POST", body: JSON.stringify({ command }) });
    setMessage("Draft created. It is NOT live until an approver publishes it."); void load();
  }
  async function publish(id: number) {
    try {
      await api(`staff/content/drafts/${id}/publish`, auth!.token, { method: "POST" });
      await load();
      setMessage("Published. Mira can now answer questions about it (it has no rates, so no price).");
    } catch (e) { setMessage(String(e)); void load(); }
  }

  return (
    <main className="staff">
      <h1>Ceylon Compass · Staff</h1>
      <div className="cc-muted">Logged in as {auth.user} ({auth.role}) · <button className="btn-link" onClick={() => { sessionStorage.removeItem("mira_staff"); setAuth(null); }}>Log out</button></div>
      <div className="tabs">
        {(["enquiries", "flags", "content"] as const).map((t) => (
          <button key={t} className={`btn ${tab === t ? "btn-primary" : ""}`} onClick={() => setTab(t)}>
            {t === "enquiries" ? `Enquiries (${enquiries.length})` : t === "flags" ? `Flags (${flags.length})` : `Content (${drafts.length})`}
          </button>
        ))}
        <button className="btn" onClick={() => void load()}>Refresh</button>
      </div>
      {message && <div className="cc-notice">{message}</div>}

      {tab === "enquiries" && (
        <table>
          <thead><tr><th>Enquiry</th><th>Quote (internal)</th><th>Flags</th><th>Notes / status</th></tr></thead>
          <tbody>
            {enquiries.map((e) => (
              <tr key={e.id}>
                <td><strong>{e.ref}</strong> <span className="badge">{e.kind}</span><div>{e.summary}</div>
                  <div className="cc-muted">{new Date(e.created_at).toLocaleString()}</div>
                  {e.contact?.name && <div className="cc-muted">Contact: {e.contact.name} · {e.contact.email}</div>}
                  <TraceLink url={e.trace_url} id={e.trace_id} token={auth.token} /></td>
                <td>{e.quote ? (<>
                  <div>Price USD {e.quote.price_usd} · deposit USD {e.quote.deposit_usd}</div>
                  <div>Cost USD {e.quote.cost_usd} · GP USD {e.quote.gross_profit_usd} ({e.quote.gross_profit_pct}%)</div>
                  {e.quote.settings_overridden.length > 0 && <div className="badge warning">settings overridden: {e.quote.settings_overridden.join(", ")}</div>}
                  <details><summary className="cc-muted">Cost lines</summary>
                    <ul className="cc-list">{e.quote.cost_lines.map((l) => <li key={l.label}>{l.label}: {l.currency} {Number(l.amount).toLocaleString()}</li>)}</ul></details>
                </>) : <span className="cc-muted">-</span>}</td>
                <td>{e.flags.map((f) => <div key={f.ref}><span className={`badge ${f.severity}`}>{f.reason}</span> <span className="cc-muted">{f.detail}</span></div>)}</td>
                <td>
                  <select value={e.status} onChange={(ev) => void setStatus(e.id, ev.target.value)}>
                    {["new", "contacted", "won", "lost"].map((s) => <option key={s}>{s}</option>)}
                  </select>
                  {e.notes.map((n, i) => <div key={i} className="cc-muted">{n.author}: {n.text}</div>)}
                  <form onSubmit={(ev) => { ev.preventDefault(); const input = ev.currentTarget.elements.namedItem("note") as HTMLInputElement; if (input.value) { void addNote(e.id, input.value); input.value = ""; } }}>
                    <input name="note" placeholder="Add a note" /> <button className="btn" type="submit">Add</button>
                  </form>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {tab === "flags" && (
        <table>
          <thead><tr><th>Flag</th><th>Reason</th><th>Detail</th><th>Trace</th></tr></thead>
          <tbody>{flags.map((f) => (
            <tr key={f.ref}><td>{f.ref}<div className="cc-muted">{f.source} · {f.tour_id || "-"}</div></td>
              <td><span className={`badge ${f.severity}`}>{f.reason}</span></td><td>{f.detail}</td>
              <td>{f.trace_url?.startsWith("http") ? <a href={f.trace_url} target="_blank" rel="noreferrer">Open</a> : f.trace_url || "-"}</td></tr>
          ))}</tbody>
        </table>
      )}

      {tab === "content" && (
        <>
          <form className="cc-card wide accent-leaf" onSubmit={(e) => { e.preventDefault(); const c = (e.currentTarget.elements.namedItem("command") as HTMLInputElement).value; void createDraft(c); }}>
            <h3 className="cc-title">Ask the content agent</h3>
            <input name="command" defaultValue="Add a 5-day Hill Country tour using the Ella photos" />
            <button className="btn btn-primary" type="submit">Create draft</button>
            <div className="cc-muted">Drafts are never shown to travellers. Only an approver can publish.</div>
          </form>
          {drafts.map((d) => (
            <div key={d.id} className="cc-card wide accent-sky">
              <div className="cc-kicker">{d.doc_id} · {d.status}{d.approved_by ? ` · approved by ${d.approved_by}` : ""}</div>
              <h3 className="cc-title">{d.title}</h3>
              <div className="cc-muted">From: &quot;{d.command}&quot; · sources: {d.sources.join(", ")}</div>
              <pre>{d.markdown}</pre>
              {d.status === "draft" && (auth.role === "approver"
                ? <button className="btn btn-primary" onClick={() => void publish(d.id)}>Approve and publish</button>
                : <div className="cc-muted">Waiting for an approver.</div>)}
            </div>
          ))}
        </>
      )}
    </main>
  );
}
