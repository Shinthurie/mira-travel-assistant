"use client";
// Traveller chat page: CopilotKit chat + our A2UI catalog. The conversation is the product.
import { CopilotChat, CopilotKitProvider, useAgent, useCopilotKit, useRenderTool } from "@copilotkit/react-core/v2";
import { useCallback, useEffect, useState } from "react";
import { z } from "zod";
import { miraCatalog } from "@/lib/catalog";

const VISITOR_COOKIE = "mira_visitor";

function readCookie(name: string): string | null {
  const m = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
  return m ? decodeURIComponent(m[1]) : null;
}

function ConsentBar({ onChange }: { onChange: (visitorId: string | null) => void }) {
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
    <div className="consent">
      {consent ? (
        <>
          <span>{returning ? `Welcome back. Say hello and I'll pick up your ${returning} quote.` : "I'll remember your trip details next time."}</span>
          <button className="btn-link" onClick={forget}>Forget me</button>
        </>
      ) : (
        <>
          <span>Can I remember your trip details for next time? Nothing is stored without your OK.</span>
          <button className="btn" onClick={allow}>Yes, remember me</button>
        </>
      )}
    </div>
  );
}

function Chat() {
  const { agent } = useAgent({ agentId: "mira" });
  const { copilotkit } = useCopilotKit();
  // The graph's render_mira_ui tool only carries A2UI operations (drawn as surfaces by the A2UI
  // renderer), so its tool-call bubble itself renders nothing.
  useRenderTool({ name: "render_mira_ui", parameters: z.object({}).passthrough(), render: () => <></> });

  const setVisitor = useCallback((visitorId: string | null) => {
    const state = { ...(agent.state || {}) } as Record<string, unknown>;
    if (visitorId) state.visitor_id = visitorId; else delete state.visitor_id;
    agent.setState(state);
  }, [agent]);

  // Buttons inside A2UI components "say" things on the traveller's behalf.
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
    <>
      <ConsentBar onChange={setVisitor} />
      <div className="chat">
        <CopilotChat agentId="mira" labels={{
          chatInputPlaceholder: "Ask about tours, or tell me your dates and who's travelling",
          chatDisclaimerText: "Prices come only from our rate sheet. Answers come only from our tour pages.",
        }} />
      </div>
    </>
  );
}

export default function Page() {
  return (
    <CopilotKitProvider runtimeUrl="/api/copilotkit" a2ui={{ catalog: miraCatalog }} enableInspector={false}>
      <main className="app">
        <header className="topbar">
          <div className="brand"><span className="brand-dot" /> Ceylon Compass Holidays <small>· Mira</small></div>
          <nav className="toplinks"><a href="/staff">Staff</a></nav>
        </header>
        <Chat />
      </main>
    </CopilotKitProvider>
  );
}
