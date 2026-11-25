"use client";
// Traveller chat page: CopilotKit chat + our A2UI catalog. The conversation is the product.
import { CopilotChat, CopilotKitProvider, useAgent, useCopilotKit, useRenderTool } from "@copilotkit/react-core/v2";
import { useCallback, useEffect, useState, type ReactElement } from "react";
import { z } from "zod";
import { miraCatalog } from "@/lib/catalog";
import { say } from "@/lib/catalog/renderers";

const VISITOR_COOKIE = "mira_visitor";

const SUGGESTIONS = [
  { label: "Price a day tour", text: "How much is the Sigiriya and Minneriya day tour from Kandy for 2 adults on 10 January 2027?" },
  { label: "Plan a family trip", text: "We're a family of four and want a custom 10 days across Kandy, Ella and the south coast." },
  { label: "See the Cultural Triangle", text: "Tell me about the Cultural Triangle Sri Lanka Package." },
  { label: "Cancellation terms", text: "What's your cancellation policy for day tours?" },
];

function readCookie(name: string): string | null {
  const m = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
  return m ? decodeURIComponent(m[1]) : null;
}

function CompassMark() {
  return (
    <svg className="mark" viewBox="0 0 32 32" aria-hidden="true">
      <circle cx="16" cy="16" r="14.5" fill="none" stroke="currentColor" strokeWidth="1.5" />
      <path d="M16 5.5 19.2 16 16 26.5 12.8 16Z" fill="var(--cc-orange)" />
      <circle cx="16" cy="16" r="1.8" fill="var(--cc-white)" />
    </svg>
  );
}

function Consent({ onChange }: { onChange: (visitorId: string | null) => void }) {
  const [consent, setConsent] = useState<boolean | null>(null);
  const [returning, setReturning] = useState<string | null>(null);

  useEffect(() => {
    const id = readCookie(VISITOR_COOKIE);
    if (!id) { setConsent(false); onChange(null); return; }
    fetch(`/api/backend/visitor/${id}`).then((r) => r.json()).then((d) => {
      setConsent(!!d.consent);
      setReturning(d.returning ? d.last_tour : null);
      onChange(d.consent ? id : null);
    }).catch(() => { setConsent(false); onChange(null); });
  }, [onChange]);

  async function allow() {
    const id = readCookie(VISITOR_COOKIE) || crypto.randomUUID();
    document.cookie = `${VISITOR_COOKIE}=${id}; path=/; max-age=${60 * 60 * 24 * 180}; samesite=lax`;
    await fetch("/api/backend/visitor/consent", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ visitor_id: id }) });
    setConsent(true); onChange(id);
  }
  async function forget() {
    const id = readCookie(VISITOR_COOKIE);
    if (id) await fetch("/api/backend/visitor/forget", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ visitor_id: id }) });
    document.cookie = `${VISITOR_COOKIE}=; path=/; max-age=0`;
    setConsent(false); setReturning(null); onChange(null);
  }
  if (consent === null) return null;
  return (
    <div className="consent" data-testid="consent">
      {consent ? (
        <>
          <p>{returning ? `Welcome back. Say hello and I'll pick up your ${returning} quote.` : <><span className="long">I'll remember your trip details next time.</span><span className="short">Remembering your trip.</span></>}</p>
          <button className="link" onClick={forget}>Forget me</button>
        </>
      ) : (
        <>
          <p><span className="long">Want me to remember your trip details next time? Nothing is stored unless you say yes.</span><span className="short">Remember my trip?</span></p>
          <button className="btn btn-small" onClick={allow}><span className="long">Yes, remember me</span><span className="short">Yes</span></button>
        </>
      )}
    </div>
  );
}

type TourItem = { id: string; title: string; duration: string };
type QuoteState = { ref: string; tour_title: string; start_date: string; adults: number; child_ages: number[];
  price_usd: string; deposit_usd: string; balance_usd: string };
type SessionState = { slots?: { tour_id?: string | null; suggested_tour_id?: string | null; adults?: number | null;
  child_ages?: number[]; start_date?: string | null }; quotes?: QuoteState[] };

/** "2125" -> "USD 2,125": formatting only, never arithmetic. The number is the engine's quote. */
function usd(value: string) { return `USD ${Number(value).toLocaleString("en-US")}`; }
function niceDate(iso: string) {
  return new Date(`${iso}T00:00:00`).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

/** Live summary of the agent's shared state (AG-UI state snapshot). The price shown is the last quote the
 *  pricing engine produced in this conversation; the state never contains cost or margin (tested). */
function TripSoFar({ tours }: { tours: TourItem[] }) {
  const { agent } = useAgent({ agentId: "mira" });
  const session = ((agent.state || {}) as { session?: SessionState }).session || {};
  const s = session.slots || {};
  const q = session.quotes?.length ? session.quotes[session.quotes.length - 1] : null;
  const tourId = s.tour_id || s.suggested_tour_id;
  const tour = q?.tour_title || tours.find((t) => t.id === tourId)?.title;
  const kids = s.child_ages?.length ? `, ${s.child_ages.length} child${s.child_ages.length > 1 ? "ren" : ""} (${s.child_ages.join(", ")})` : "";
  const who = s.adults ? `${s.adults} adult${s.adults > 1 ? "s" : ""}${kids}` : null;
  const start = q?.start_date || s.start_date;
  if (!tour && !who && !start) {
    return <p className="side-empty">Nothing yet. Tell Mira where you&apos;d like to go, when, and who&apos;s coming.</p>;
  }
  return (
    <dl className="trip">
      <dt>Tour</dt><dd>{tour || <span className="cc-muted">Not chosen yet</span>}</dd>
      <dt>Who</dt><dd>{who || <span className="cc-muted">Not known yet</span>}</dd>
      <dt>Starts</dt><dd>{start ? niceDate(start) : <span className="cc-muted">No date yet</span>}</dd>
      <dt>Price</dt>
      <dd>{q ? <><b>{usd(q.price_usd)}</b><small>Deposit {usd(q.deposit_usd)} · {q.ref}</small></> : <span className="cc-muted">Not priced yet</span>}</dd>
    </dl>
  );
}

/** Desktop side panel: four collapsible sections, one open at a time (no scrolling). */
function SidePanel() {
  const [tours, setTours] = useState<TourItem[]>([]);
  useEffect(() => {
    fetch("/api/backend/tours").then((r) => r.json()).then(setTours).catch(() => setTours([]));
  }, []);
  return (
    <div className="side-sections">
      <details name="side" open>
        <summary>Your trip so far</summary>
        <TripSoFar tours={tours} />
      </details>
      <details name="side">
        <summary>How booking works</summary>
        <ol className="side-steps">
          <li><strong>Tell Mira your trip.</strong> Where, when and who&apos;s coming.</li>
          <li><strong>Get a confirmed price.</strong> Worked out from our current rate sheet.</li>
          <li><strong>Book with a deposit.</strong> Or a specialist confirms anything we can&apos;t price.</li>
        </ol>
      </details>
      <details name="side">
        <summary>Popular tours</summary>
        <ul className="side-tours">
          {tours.slice(0, 4).map((t) => (
            <li key={t.id}><button onClick={() => say(`Tell me about the ${t.title}.`)}>
              <span>{t.title}</span><small>{t.duration}</small></button></li>
          ))}
        </ul>
      </details>
      <details name="side">
        <summary>Our promises</summary>
        <ul className="side-promises">
          <li><strong>Real prices only.</strong> Never guessed.</li>
          <li><strong>Sources shown.</strong> From our own tour pages.</li>
          <li><strong>A person when it counts.</strong> A specialist picks it up.</li>
        </ul>
      </details>
    </div>
  );
}

/** Replaces CopilotKit's default welcome: our greeting, starter questions, then the input. */
function Welcome({ input }: { input: ReactElement }) {
  return (
    <div className="welcome" data-testid="welcome">
      <div className="welcome-inner">
        <p className="welcome-kicker">Ceylon Compass Holidays</p>
        <h1>Hello, I&apos;m Mira.</h1>
        <p className="welcome-lede">Tell me where you&apos;d like to go and who&apos;s coming. I&apos;ll find the right tour and give you a confirmed price.</p>
        <div className="starters">
          {SUGGESTIONS.map((s) => (
            <button key={s.label} className="starter" onClick={() => say(s.text)}>
              <span className="starter-label">{s.label}</span>
              <span className="starter-text">{s.text}</span>
            </button>
          ))}
        </div>
      </div>
      <div className="welcome-input">{input}</div>
      <a className="welcome-staff" href="/staff">Staff login</a>
    </div>
  );
}

function Chat({ onVisitor }: { onVisitor: (setter: (id: string | null) => void) => void }) {
  const { agent } = useAgent({ agentId: "mira" });
  const { copilotkit } = useCopilotKit();
  // CopilotKit sizes the input to fit its placeholder, so phones get a short one (a one-line composer).
  const [narrow, setNarrow] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia("(max-width: 560px)");
    const update = () => setNarrow(mq.matches);
    update(); mq.addEventListener("change", update);
    return () => mq.removeEventListener("change", update);
  }, []);
  // The graph's render_mira_ui tool only carries A2UI operations (drawn as surfaces by the A2UI
  // renderer), so its tool-call bubble itself renders nothing.
  useRenderTool({ name: "render_mira_ui", parameters: z.object({}).passthrough(), render: () => <></> });

  const setVisitor = useCallback((visitorId: string | null) => {
    const state = { ...(agent.state || {}) } as Record<string, unknown>;
    if (visitorId) state.visitor_id = visitorId; else delete state.visitor_id;
    agent.setState(state);
  }, [agent]);
  useEffect(() => onVisitor(setVisitor), [onVisitor, setVisitor]);

  // Buttons inside A2UI components (and the starters) "say" things on the traveller's behalf.
  useEffect(() => {
    const onSay = (e: Event) => {
      const text = (e as CustomEvent<string>).detail;
      agent.addMessage({ id: crypto.randomUUID(), role: "user", content: text });
      void copilotkit.runAgent({ agent });
    };
    window.addEventListener("mira:say", onSay);
    return () => window.removeEventListener("mira:say", onSay);
  }, [agent, copilotkit]);

  return (
    <div className="chat">
      <CopilotChat
        key={narrow ? "narrow" : "wide"}  // re-measure the input when the placeholder changes
        agentId="mira"
        welcomeScreen={Welcome as never}
        labels={{
          chatInputPlaceholder: narrow ? "Message Mira…" : "Ask about a tour, or tell me your dates and who's travelling",
          chatDisclaimerText: "Prices come from our rate sheet. Answers come from our tour pages.",
        }}
      />
    </div>
  );
}

export default function Page() {
  const [visitorSetter, setVisitorSetter] = useState<((id: string | null) => void) | null>(null);
  const registerSetter = useCallback((fn: (id: string | null) => void) => setVisitorSetter(() => fn), []);
  const onConsent = useCallback((id: string | null) => visitorSetter?.(id), [visitorSetter]);
  // Small screens: the side panel is hidden behind a menu button and opens below the header.
  const [menuOpen, setMenuOpen] = useState(false);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setMenuOpen(false); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <CopilotKitProvider runtimeUrl="/api/copilotkit" a2ui={{ catalog: miraCatalog }} enableInspector={false}>
      <div className={`shell${menuOpen ? " side-open" : ""}`}>
        <aside className="side">
          <button className="menu-btn" aria-label={menuOpen ? "Close menu" : "Open menu"} aria-expanded={menuOpen}
            aria-controls="side-body" onClick={() => setMenuOpen(!menuOpen)}>
            <svg viewBox="0 0 24 24" aria-hidden="true">
              {menuOpen ? <path d="M6 6l12 12M18 6L6 18" /> : <path d="M4 7h16M4 12h16M4 17h16" />}
            </svg>
          </button>
          <a className="brand" href="/"><CompassMark /><span>Ceylon Compass<small>Holidays</small></span></a>
          <div className="side-body" id="side-body">
            <h2>Plan and price your Sri Lanka trip in one conversation.</h2>
            <SidePanel />
          </div>
          {visitorSetter && <Consent onChange={onConsent} />}
          <footer className="side-foot">
            <span>Prices in US dollars, per booking.</span>
            <a href="/staff">Staff login</a>
          </footer>
        </aside>
        <main className="main">
          <header className="topbar">
            <a className="brand" href="/"><CompassMark /><span>Ceylon Compass<small>Holidays</small></span></a>
            <a className="topbar-link" href="/staff">Staff</a>
          </header>
          <Chat onVisitor={registerSetter} />
        </main>
      </div>
    </CopilotKitProvider>
  );
}
