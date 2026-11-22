"use client";
// React renderers for Mira's catalog. Each one re-validates its resolved props with zod and shows a
// plain-text fallback if they don't match (and logs it), so a bad payload never breaks the page.
import { useState } from "react";
import { z } from "zod";
import { resolved, type ComponentName } from "./definitions";

/** Send a message to Mira as if the traveller typed it (handled in app/page.tsx). */
export function say(text: string) {
  window.dispatchEvent(new CustomEvent("mira:say", { detail: text }));
}

const fmtUsd = (v: string) => `USD ${Number(v).toLocaleString("en-US", { maximumFractionDigits: 2 })}`;
const fmtDate = (iso?: string | null) =>
  iso ? new Date(`${iso}T00:00:00`).toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" }) : "";

function useValid<N extends ComponentName>(name: N, props: unknown): z.SafeParseReturnType<unknown, z.infer<(typeof resolved)[N]>> {
  const schema = resolved[name] as unknown as z.ZodType<z.infer<(typeof resolved)[N]>>;
  // The A2UI binder adds a `set<Prop>` function per bound prop (two-way binding). Drop functions;
  // every DATA key is still validated strictly (unknown data keys are rejected).
  const data = Object.fromEntries(Object.entries((props ?? {}) as Record<string, unknown>)
    .filter(([, v]) => typeof v !== "function"));
  const result = schema.safeParse(data);
  if (!result.success) {
    console.warn(`[Mira] ${name} props failed client validation ${JSON.stringify(result.error.issues).slice(0, 400)}`);
    window.dispatchEvent(new CustomEvent("mira:ui-invalid", { detail: { name, issues: result.error.issues } }));
  }
  return result;
}

const Fallback = ({ name }: { name: string }) => (
  <div className="cc-fallback">This {name} couldn&apos;t be shown. The details are in Mira&apos;s message.</div>
);

function PriceBreakdown({ props }: { props: unknown }) {
  const v = useValid("PriceBreakdown", props);
  if (!v.success) return <Fallback name="price" />;
  const p = v.data;
  return (
    <div className={`cc-card wide accent-${p.accent}`} data-testid="price-breakdown">
      <div className="cc-kicker">Confirmed price · {p.quote_ref}</div>
      <h3 className="cc-title">{p.tour_title}</h3>
      <div className="cc-muted">{fmtDate(p.start_date)} to {fmtDate(p.end_date)} · {p.duration}</div>
      <div className="cc-muted">{p.travellers_summary}</div>
      <div className="cc-price">{fmtUsd(p.price_usd)}</div>
      <div className="cc-muted">Total for your group</div>
      {p.pay_in_full ? (
        <div className="cc-row"><span>Pay in full when you book</span><strong>{fmtUsd(p.deposit_usd)}</strong></div>
      ) : (
        <>
          <div className="cc-row"><span>Deposit to confirm</span><strong>{fmtUsd(p.deposit_usd)}</strong></div>
          <div className="cc-row"><span>Balance due {fmtDate(p.balance_due_date)}</span><strong>{fmtUsd(p.balance_usd)}</strong></div>
        </>
      )}
      {p.inclusions.length > 0 && (
        <details>
          <summary className="cc-muted">What&apos;s included</summary>
          <ul className="cc-list">{p.inclusions.map((x) => <li key={x}>{x}</li>)}</ul>
        </details>
      )}
      <div className="cc-actions">
        <button className="btn btn-primary" onClick={() => say("I'd like to book it.")}>Book this</button>
      </div>
    </div>
  );
}

function BookingForm({ props }: { props: unknown }) {
  const v = useValid("BookingForm", props);
  const [state, setState] = useState<{ status: "idle" | "sending" | "done" | "failed"; message?: string; steps?: string[]; ref?: string }>({ status: "idle" });
  if (!v.success) return <Fallback name="booking form" />;
  const p = v.data;
  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    setState({ status: "sending" });
    try {
      const forceFail = new URLSearchParams(window.location.search).get("failpay") === "1";
      const res = await fetch("/api/backend/booking", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          quote_ref: p.quote_ref, name: form.get("name"), email: form.get("email"), phone: form.get("phone") || null,
          notes: form.get("notes") || null, consent: form.get("consent") === "on", force_fail: forceFail,
        }),
      });
      const data = await res.json();
      setState(data.ok ? { status: "done", ref: data.enquiry_ref, steps: data.next_steps, message: data.summary }
        : { status: "failed", message: data.message, steps: data.next_steps });
    } catch {
      setState({ status: "failed", message: "We couldn't reach our booking system. Nothing has been charged.",
        steps: ["Try again in a minute", "Or ask Mira to pass your request to a specialist"] });
    }
  }
  if (state.status === "done") {
    return (
      <div className={`cc-card accent-${p.accent}`}>
        <div className="cc-kicker">Booking request {state.ref}</div>
        <h3 className="cc-title">Thank you</h3>
        <ul className="cc-list">{state.steps?.map((s) => <li key={s}>{s}</li>)}</ul>
      </div>
    );
  }
  return (
    <form className={`cc-card accent-${p.accent}`} onSubmit={submit} data-testid="booking-form">
      <div className="cc-kicker">Book · {p.quote_ref}</div>
      <h3 className="cc-title">{p.tour_title}</h3>
      <div className="cc-row"><span>{p.pay_in_full ? "Pay in full" : "Deposit today"}</span><strong>{fmtUsd(p.deposit_usd)}</strong></div>
      <label className="cc-field">Name<input name="name" required maxLength={120} autoComplete="name" /></label>
      <label className="cc-field">Email<input name="email" type="email" required autoComplete="email" /></label>
      <label className="cc-field">Phone (optional)<input name="phone" autoComplete="tel" /></label>
      <label className="cc-field">Notes (optional)<textarea name="notes" rows={2} /></label>
      <label className="cc-muted"><input type="checkbox" name="consent" required /> {p.consent_text}</label>
      {state.status === "failed" && (
        <div className="cc-notice" role="alert">
          <div>{state.message}</div>
          <ul className="cc-list">{state.steps?.map((s) => <li key={s}>{s}</li>)}</ul>
        </div>
      )}
      <div className="cc-actions">
        <button className="btn btn-primary" type="submit" disabled={state.status === "sending"}>
          {state.status === "sending" ? "Sending..." : state.status === "failed" ? "Try again" : "Pay and book (demo)"}
        </button>
        {state.status === "failed" && (
          <button className="btn" type="button" onClick={() => say("Please ask a specialist to contact me to finish my booking.")}>
            Ask a specialist
          </button>
        )}
      </div>
    </form>
  );
}

function SpecialistHandoff({ props }: { props: unknown }) {
  const v = useValid("SpecialistHandoff", props);
  if (!v.success) return <Fallback name="message" />;
  const p = v.data;
  return (
    <div className={`cc-card accent-${p.accent}`} data-testid="specialist-handoff">
      <div className="cc-kicker">No price yet</div>
      <h3 className="cc-title">{p.title}</h3>
      {p.tour_title && <div><strong>{p.tour_title}</strong></div>}
      <div className="cc-muted">{p.reason_text}</div>
      <div className="cc-muted">Your request is saved{p.enquiry_ref ? ` (${p.enquiry_ref})` : ""}. A specialist will get back to you.</div>
      <div className="cc-actions">
        <button className="btn" onClick={() => say("Please ask a specialist to contact me.")}>{p.cta_label}</button>
      </div>
    </div>
  );
}

function EnquiryConfirmation({ props }: { props: unknown }) {
  const v = useValid("EnquiryConfirmation", props);
  if (!v.success) return <Fallback name="confirmation" />;
  const p = v.data;
  return (
    <div className={`cc-card accent-${p.accent}`}>
      <div className="cc-kicker">Saved · {p.enquiry_ref}</div>
      <h3 className="cc-title">{p.summary}</h3>
      <ul className="cc-list">{p.next_steps.map((s) => <li key={s}>{s}</li>)}</ul>
    </div>
  );
}

function TourCard({ props }: { props: unknown }) {
  const v = useValid("TourCard", props);
  if (!v.success) return <Fallback name="tour" />;
  const p = v.data;
  return (
    <div className={`cc-card accent-${p.accent}`} data-testid="tour-card">
      <div className="cc-image" aria-label="Photo placeholder">Photo coming soon</div>
      <div className="cc-kicker">{p.category} · {p.duration}</div>
      <h3 className="cc-title">{p.title}</h3>
      <div className="cc-muted">{p.summary}</div>
      <div className="cc-chips">{p.places.map((x) => <span key={x} className="cc-chip">{x}</span>)}</div>
      <div className="cc-actions">
        {p.priceable ? (
          <button className="btn btn-primary" onClick={() => say(`I'd like a price for ${p.title}.`)}>Get a price</button>
        ) : (
          <button className="btn" onClick={() => say(`Please ask a specialist about ${p.title}.`)}>Ask a specialist</button>
        )}
        <button className="btn" onClick={() => say(`Tell me about ${p.title}.`)}>Details</button>
      </div>
    </div>
  );
}

function ItineraryDay({ props }: { props: unknown }) {
  const v = useValid("ItineraryDay", props);
  if (!v.success) return <Fallback name="itinerary day" />;
  const p = v.data;
  return (
    <div className={`cc-card accent-${p.accent}`}>
      <div className="cc-kicker">Day {p.day_number}</div>
      <h3 className="cc-title">{p.title}</h3>
      <div className="cc-muted">{p.description}</div>
      {p.meals.length > 0 && <div className="cc-row"><span>Meals</span><span>{p.meals.join(", ")}</span></div>}
      {p.accommodation && <div className="cc-row"><span>Stay</span><span>{p.accommodation}</span></div>}
    </div>
  );
}

function TravellerPicker({ props }: { props: unknown }) {
  const v = useValid("TravellerPicker", props);
  const ok = v.success;
  const [adults, setAdults] = useState(ok ? v.data.adults_default : 2);
  const [kids, setKids] = useState<number[]>(ok ? v.data.child_ages_default : []);
  if (!ok) return <Fallback name="traveller picker" />;
  const p = v.data;
  const total = adults + kids.filter((a) => a >= 2).length;
  function send() {
    const childText = kids.length ? ` and ${kids.length} ${kids.length === 1 ? "child" : "children"} aged ${kids.join(" and ")}` : " and no children";
    say(`We are ${adults} adults${childText}.`);
  }
  return (
    <div className={`cc-card accent-${p.accent}`} data-testid="traveller-picker">
      <div className="cc-kicker">Travellers</div>
      <h3 className="cc-title">{p.prompt}</h3>
      <div className="cc-row"><span>Adults (12+)</span>
        <span className="cc-stepper">
          <button aria-label="fewer adults" onClick={() => setAdults(Math.max(1, adults - 1))}>-</button>{adults}
          <button aria-label="more adults" onClick={() => total < p.max_group && setAdults(adults + 1)}>+</button>
        </span>
      </div>
      {kids.map((age, i) => (
        <div className="cc-row" key={i}><span>Child {i + 1} age</span>
          <span className="cc-stepper">
            <button aria-label="younger" onClick={() => setKids(kids.map((a, j) => (j === i ? Math.max(0, a - 1) : a)))}>-</button>{age}
            <button aria-label="older" onClick={() => setKids(kids.map((a, j) => (j === i ? Math.min(11, a + 1) : a)))}>+</button>
            <button aria-label="remove child" onClick={() => setKids(kids.filter((_, j) => j !== i))}>x</button>
          </span>
        </div>
      ))}
      <div className="cc-actions">
        <button className="btn" onClick={() => total < p.max_group && setKids([...kids, 6])}>Add a child</button>
        <button className="btn btn-primary" onClick={send}>Use these</button>
      </div>
      <div className="cc-muted">Up to {p.max_group} travellers. Children under 2 travel free.</div>
    </div>
  );
}

function SourceCitation({ props }: { props: unknown }) {
  const v = useValid("SourceCitation", props);
  if (!v.success) return <Fallback name="sources" />;
  const p = v.data;
  return (
    <div className={`cc-card accent-${p.accent}`} data-testid="source-citation">
      <div className="cc-kicker">Sources</div>
      <ul className="cc-list">
        {p.sources.map((s) => <li key={s.passage_id}>{s.title} · {s.section} <span className="cc-muted">({s.doc_id})</span></li>)}
      </ul>
    </div>
  );
}

export const renderers = {
  PriceBreakdown, BookingForm, SpecialistHandoff, EnquiryConfirmation, TourCard, ItineraryDay, TravellerPicker,
  SourceCitation,
};
