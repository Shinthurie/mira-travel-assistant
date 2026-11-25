"use client";
// React renderers for Mira's catalog. Each one re-validates its resolved props with zod and shows a
// plain-text fallback if they don't match (and logs it), so a bad payload never breaks the page.
import { useState, type ReactNode } from "react";
import { z } from "zod";
import { resolved, type ComponentName } from "./definitions";

/** Send a message to Mira as if the traveller typed it (handled in app/page.tsx). */
export function say(text: string) {
  window.dispatchEvent(new CustomEvent("mira:say", { detail: text }));
}

const usd = (v: string) => Number(v).toLocaleString("en-US", { maximumFractionDigits: 2 });
const longDate = (iso?: string | null) =>
  iso ? new Date(`${iso}T00:00:00`).toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" }) : "";
const shortDate = (iso?: string | null) =>
  iso ? new Date(`${iso}T00:00:00`).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" }) : "";

type Valid<N extends ComponentName> = z.SafeParseReturnType<unknown, z.infer<(typeof resolved)[N]>>;

function useValid<N extends ComponentName>(name: N, props: unknown): Valid<N> {
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
  <div className="cc-fallback">This {name} couldn&apos;t be shown. The details are in Mira&apos;s message above.</div>
);

function Card({ accent, children, testid, className }: {
  accent: string; children: ReactNode; testid?: string; className?: string;
}) {
  return <div className={className ?? `cc-card accent-${accent}`} data-testid={testid}>{children}</div>;
}

// ---------- Fixed schema: money and bookings ----------------------------------------------

function PriceBreakdown({ props }: { props: unknown }) {
  const v = useValid("PriceBreakdown", props);
  if (!v.success) return <Fallback name="price" />;
  const p = v.data;
  return (
    <Card accent={p.accent} testid="price-breakdown" className={`cc-card accent-${p.accent} cc-card-wide`}>
      <div className="cc-kicker">Confirmed price</div>
      <div className="pkg-cols">
      <div className="pkg-col">
      <div>
        <h3 className="cc-title">{p.tour_title}</h3>
        <p className="cc-sub">{p.travellers_summary}</p>
      </div>
      <div className="price-total"><span className="cur">USD</span><span className="amount num">{usd(p.price_usd)}</span></div>
      <dl className="facts">
        <dt>Dates</dt><dd>{p.start_date === p.end_date ? shortDate(p.start_date) : `${shortDate(p.start_date)} – ${shortDate(p.end_date)}`}</dd>
        <dt>Length</dt><dd>{p.duration}</dd>
        <dt>Quote</dt><dd className="num">{p.quote_ref}</dd>
      </dl>
      </div>
      <div className="pkg-col">
      <p className="pkg-head">How you pay</p>
      {p.pay_in_full ? (
        <ul className="plan">
          <li><span className="dot" /><span>Pay in full when you book</span><strong className="num">USD {usd(p.deposit_usd)}</strong></li>
        </ul>
      ) : (
        <ul className="plan">
          <li><span className="dot" /><span>Deposit to confirm</span><strong className="num">USD {usd(p.deposit_usd)}</strong></li>
          <li><span className="dot" /><span>Balance by {shortDate(p.balance_due_date)}</span><strong className="num">USD {usd(p.balance_usd)}</strong></li>
        </ul>
      )}
      {p.inclusions.length > 0 && (
        <div className="pkg-block"><p className="pkg-head">What&apos;s included</p>
          <ul>{p.inclusions.map((x) => <li key={x}><Icon name="check" />{x}</li>)}</ul></div>
      )}
      <button className="btn btn-primary btn-block" onClick={() => say("I'd like to book it.")}>Book this trip</button>
      </div>
      </div>
    </Card>
  );
}

type BookingState = { status: "idle" | "sending" | "done" | "failed"; message?: string; steps?: string[]; ref?: string };

function BookingForm({ props }: { props: unknown }) {
  const v = useValid("BookingForm", props);
  const [state, setState] = useState<BookingState>({ status: "idle" });
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
      setState(data.ok ? { status: "done", ref: data.enquiry_ref, steps: data.next_steps }
        : { status: "failed", message: data.message, steps: data.next_steps });
    } catch {
      setState({ status: "failed", message: "We couldn't reach our booking system. Nothing has been charged.",
        steps: ["Try again in a minute", "Or ask Mira to pass your request to a specialist"] });
    }
  }

  if (state.status === "done") {
    return (
      <Card accent="leaf" testid="booking-done">
        <div className="cc-kicker">Booking request {state.ref}</div>
        <h3 className="cc-title">Thank you. Your request is in.</h3>
        <ol className="steps">{state.steps?.map((s) => <li key={s}>{s}</li>)}</ol>
      </Card>
    );
  }
  return (
    <form className={`cc-card accent-${p.accent}`} data-testid="booking-form" onSubmit={submit}>
      <div className="cc-kicker">Book · {p.quote_ref}</div>
      <div>
        <h3 className="cc-title">{p.tour_title}</h3>
        <p className="cc-sub num">{p.pay_in_full ? "Paid in full today" : "Deposit today"}: USD {usd(p.deposit_usd)}</p>
      </div>
      <label className="field">Full name<input name="name" required maxLength={120} autoComplete="name" /></label>
      <label className="field">Email<input name="email" type="email" required autoComplete="email" /></label>
      <label className="field">Phone <span className="cc-muted">(optional)</span><input name="phone" autoComplete="tel" /></label>
      <label className="field">Anything we should know? <span className="cc-muted">(optional)</span><textarea name="notes" rows={2} /></label>
      <label className="check"><input type="checkbox" name="consent" required /> <span>{p.consent_text}</span></label>
      {state.status === "failed" && (
        <div className="cc-notice" role="alert">
          <strong>{state.message}</strong>
          <ol className="steps">{state.steps?.map((s) => <li key={s}>{s}</li>)}</ol>
        </div>
      )}
      <div className="cc-actions">
        <button className="btn btn-primary" type="submit" disabled={state.status === "sending"}>
          {state.status === "sending" ? "Sending…" : state.status === "failed" ? "Try again" : "Pay and book (demo)"}
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
    <Card accent={p.accent} testid="specialist-handoff">
      <div className="cc-kicker">A specialist will confirm</div>
      <div>
        <h3 className="cc-title">{p.tour_title || "We'll check this for you"}</h3>
        <p className="cc-sub">{p.reason_text}</p>
      </div>
      <ol className="steps">
        <li>Your request is saved{p.enquiry_ref ? ` as ${p.enquiry_ref}` : ""}.</li>
        <li>A specialist checks the rates with our hotels.</li>
        <li>They get back to you with a confirmed price.</li>
      </ol>
      <button className="btn" onClick={() => say("Please ask a specialist to contact me.")}>{p.cta_label}</button>
    </Card>
  );
}

function EnquiryConfirmation({ props }: { props: unknown }) {
  const v = useValid("EnquiryConfirmation", props);
  if (!v.success) return <Fallback name="confirmation" />;
  const p = v.data;
  return (
    <Card accent={p.accent} testid="enquiry-confirmation">
      <div className="cc-kicker">Saved · {p.enquiry_ref}</div>
      <h3 className="cc-title">{p.summary}</h3>
      <ol className="steps">{p.next_steps.map((s) => <li key={s}>{s}</li>)}</ol>
    </Card>
  );
}

// ---------- Dynamic schema: content ----------------------------------------------------------

/** A quiet "route line" in the card's accent: one dot per place. Honest stand-in for a photo. */
function RouteArt({ seed, stops }: { seed: string; stops: number }) {
  let h = 0;
  for (const ch of seed) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  const n = Math.max(2, Math.min(stops, 6));
  const pts = Array.from({ length: n }, (_, i) => {
    h = (h * 1103515245 + 12345) >>> 0;
    return [24 + (i * 272) / (n - 1), 26 + (h % 40)] as const;
  });
  const d = pts.map(([x, y], i) => (i === 0 ? `M${x},${y}` : `Q${(pts[i - 1][0] + x) / 2},${y - 18} ${x},${y}`)).join(" ");
  return (
    <div className="tour-art" aria-hidden="true">
      <svg viewBox="0 0 320 92" preserveAspectRatio="none">
        <path d={d} fill="none" stroke="var(--accent)" strokeWidth="2" strokeDasharray="5 6" strokeLinecap="round" />
        {pts.map(([x, y], i) => <circle key={i} cx={x} cy={y} r={i === 0 || i === n - 1 ? 5 : 3.5} fill="var(--cc-white)" stroke="var(--accent)" strokeWidth="2" />)}
      </svg>
      <span className="art-note">Photos to come</span>
    </div>
  );
}

/** Outlined line icons (stroke only, brand orange), drawn inline: no emoji, no icon font. */
const ICONS: Record<string, string> = {
  clock: "M8 4.5V8l2.5 1.5M14.5 8a6.5 6.5 0 1 1-13 0 6.5 6.5 0 0 1 13 0Z",
  pin: "M8 14.5s4.5-4.2 4.5-8a4.5 4.5 0 0 0-9 0c0 3.8 4.5 8 4.5 8Zm0-6.5a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3Z",
  route: "M3.5 12.5a1.5 1.5 0 1 0 0 .01M12.5 3.5a1.5 1.5 0 1 0 0 .01M3.5 11V7a2 2 0 0 1 2-2h5M12.5 5v4a2 2 0 0 1-2 2h-5",
  info: "M8 7.2v4M8 4.8v.01M14.5 8a6.5 6.5 0 1 1-13 0 6.5 6.5 0 0 1 13 0Z",
  check: "M3.5 8.5l3 3 6-7",
  map: "M1.5 3.5l4-1.5 5 2 4-1.5v10l-4 1.5-5-2-4 1.5v-10ZM5.5 2v10.5M10.5 4v10.5",
};
function Icon({ name }: { name: keyof typeof ICONS }) {
  return <svg className="line-icon" viewBox="0 0 16 16" aria-hidden="true"><path d={ICONS[name]} /></svg>;
}

function TourCardView({ p }: { p: z.infer<(typeof resolved)["TourCard"]> }) {
  // One box per tour. Closed: the essentials (brand card width). "Details" opens everything in place,
  // full chat width, including the day-by-day plan; no new message is sent.
  const [open, setOpen] = useState(!!p.expanded);
  const d = p.details;
  const included = d?.included?.length ? d.included : (p.included || []);
  const days = d?.days || [];
  const priceButton = p.priceable ? (
    <button className="btn btn-primary" onClick={() => say(`I'd like a price for ${p.title}.`)}>Get a price</button>
  ) : (
    <button className="btn" onClick={() => say(`Please ask a specialist about ${p.title}.`)}>Ask a specialist</button>
  );
  return (
    <Card accent={p.accent} testid="tour-card" className={`cc-card accent-${p.accent}${open ? " cc-card-wide" : ""}`}>
      {!open && <RouteArt seed={p.tour_id} stops={p.places.length} />}
      <div className="cc-kicker">{p.category} · {p.duration}</div>
      {open || !d ? <h3 className="cc-title">{p.title}</h3> : (
        <h3 className="cc-title"><button className="title-link" aria-expanded={false} onClick={() => setOpen(true)}>{p.title}</button></h3>
      )}
      {!open && (
        <>
          <p className="tour-summary">{p.summary}</p>
          {d?.start && <p className="tour-start"><Icon name="pin" />{d.start}</p>}
          <div className="chips">{p.places.map((x) => <span key={x} className="chip">{x}</span>)}</div>
          {p.included && p.included.length > 0 && (
            <div className="included">
              <p className="included-head">What&apos;s included</p>
              <ul>{included.map((x) => <li key={x}><Icon name="check" />{x}</li>)}</ul>
            </div>
          )}
        </>
      )}
      {open && d && (
        <div className="pkg" data-testid="tour-details">
          <div className="pkg-cols">
            <div className="pkg-col">
              {d.about && <p className="pkg-about">{d.about}</p>}
              <ul className="pkg-facts">
                <li><Icon name="clock" /><span><b>Duration</b>{p.duration}</span></li>
                {d.start && <li><Icon name="pin" /><span><b>Starts from</b>{d.start}</span></li>}
                {p.places.length > 0 && <li><Icon name="map" /><span><b>Places</b>{p.places.join(" · ")}</span></li>}
              </ul>
            </div>
            <div className="pkg-col">
              {included.length > 0 && (
                <div className="pkg-block"><p className="pkg-head">What&apos;s included</p>
                  <ul>{included.map((x) => <li key={x}><Icon name="check" />{x}</li>)}</ul></div>
              )}
              {d.good_to_know.length > 0 && (
                <div className="pkg-block"><p className="pkg-head">Good to know</p>
                  <ul>{d.good_to_know.map((x) => <li key={x}><Icon name="info" />{x}</li>)}</ul></div>
              )}
              {d.route.length > 0 && (
                <div className="pkg-block"><p className="pkg-head">Route</p>
                  <ul>{d.route.map((x) => <li key={x}><Icon name="route" />{x}</li>)}</ul></div>
              )}
            </div>
          </div>
          {days.length > 0 && (
            <details className="pkg-block pkg-days-wrap"><summary className="pkg-head">Day by day · {days.length} days</summary>
              <ol className="pkg-days">
                {days.map((x) => (
                  <li key={x.day}>
                    <span className="pkg-day-num">{x.day}</span>
                    <div>
                      <strong>{x.title}</strong>
                      {x.description && <p>{x.description}</p>}
                      {(x.meals.length > 0 || x.stay) && (
                        <p className="pkg-day-meta">{[x.meals.length ? `Meals: ${x.meals.join(", ")}` : "", x.stay ? `Stay: ${x.stay}` : ""].filter(Boolean).join(" · ")}</p>
                      )}
                    </div>
                  </li>
                ))}
              </ol>
            </details>
          )}
        </div>
      )}
      <div className="cc-actions">
        {priceButton}
      </div>
    </Card>
  );
}

function TourCard({ props }: { props: unknown }) {
  const v = useValid("TourCard", props);
  if (!v.success) return <Fallback name="tour" />;
  return <TourCardView p={v.data} />;
}

function TourShelf({ props }: { props: unknown }) {
  const v = useValid("TourShelf", props);
  if (!v.success) return <Fallback name="tour list" />;
  return (
    <section className="shelf" data-testid="tour-shelf">
      <h3 className="shelf-head">{v.data.title}</h3>
      <div className="shelf-row">{v.data.tours.map((t) => <TourCardView key={t.tour_id} p={t} />)}</div>
    </section>
  );
}

function ItineraryDay({ props }: { props: unknown }) {
  const v = useValid("ItineraryDay", props);
  if (!v.success) return <Fallback name="itinerary day" />;
  const p = v.data;
  return (
    <Card accent={p.accent} testid="itinerary-day" className={`cc-card accent-${p.accent} day`}>
      <div className="day-num"><span>Day</span><b>{p.day_number}</b></div>
      <div className="day-body">
        <h3 className="cc-title" style={{ fontSize: "var(--cc-text-md)" }}>{p.title}</h3>
        <p className="cc-sub">{p.description}</p>
        {p.meals.length > 0 && <p className="cc-muted">Meals: {p.meals.join(", ")}</p>}
        {p.accommodation && <p className="cc-muted">Stay: {p.accommodation}</p>}
      </div>
    </Card>
  );
}

function TravellerPicker({ props }: { props: unknown }) {
  const v = useValid("TravellerPicker", props);
  const ok = v.success;
  const [adults, setAdults] = useState(ok ? v.data.adults_default : 2);
  const [kids, setKids] = useState<number[]>(ok ? v.data.child_ages_default : []);
  const [start, setStart] = useState("");
  if (!ok) return <Fallback name="traveller picker" />;
  const p = v.data;
  const total = adults + kids.filter((a) => a >= 2).length;
  const needDate = !!p.ask_date;
  function send() {
    const childText = kids.length ? ` and ${kids.length} ${kids.length === 1 ? "child" : "children"} aged ${kids.join(" and ")}` : " and no children";
    // "12 April 2027": the wording both the model and the rule-based extractor read reliably.
    const when = needDate && start
      ? `, starting ${new Date(`${start}T00:00:00`).toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" })}` : "";
    say(`We are ${adults} adults${childText}${when}.`);
  }
  return (
    <Card accent={p.accent} testid="traveller-picker" className={`cc-card accent-${p.accent}${needDate ? " cc-card-wide" : ""}`}>
      <div className="cc-kicker">{p.ask_date ? "Travellers and date" : "Travellers"}</div>
      <h3 className="cc-title">{p.prompt}</h3>
      <div className={needDate ? "pkg-cols" : "picker-one"}>
      <div className="pkg-col">
      <div className="counter">
        <div>Adults<small>12 and over</small></div>
        <span className="stepper">
          <button aria-label="Fewer adults" onClick={() => setAdults(Math.max(1, adults - 1))}>−</button>
          <output>{adults}</output>
          <button aria-label="More adults" onClick={() => total < p.max_group && setAdults(adults + 1)}>+</button>
        </span>
      </div>
      {kids.map((age, i) => (
        <div className="counter" key={i}>
          <div>Child {i + 1}<small>{age < 2 ? "under 2, travels free" : `aged ${age}`}</small></div>
          <span className="stepper">
            <button aria-label="Younger" onClick={() => setKids(kids.map((a, j) => (j === i ? Math.max(0, a - 1) : a)))}>−</button>
            <output>{age}</output>
            <button aria-label="Older" onClick={() => setKids(kids.map((a, j) => (j === i ? Math.min(11, a + 1) : a)))}>+</button>
          </span>
        </div>
      ))}
      <div className="cc-actions">
        <button className="btn" onClick={() => total < p.max_group && setKids([...kids, 6])}>Add a child</button>
        {kids.length > 0 && <button className="link" onClick={() => setKids(kids.slice(0, -1))}>Remove last child</button>}
      </div>
      </div>
      <div className="pkg-col">
      {needDate && (
        <label className="field date-field">
          <span>Start date</span>
          <input type="date" value={start} min={p.date_min || undefined} max={p.date_max || undefined}
            onChange={(e) => setStart(e.target.value)} required />
          {p.date_max && <small className="cc-muted">Bookable until {new Date(`${p.date_max}T00:00:00`).toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric" })} on our current rates.</small>}
        </label>
      )}
      <button className="btn btn-primary btn-block" onClick={send} disabled={needDate && !start}>
        {needDate ? "Get my price" : "Use these travellers"}</button>
      <p className="cc-muted">Private tours are for up to {p.max_group} travellers.</p>
      </div>
      </div>
    </Card>
  );
}

function SourceCitation({ props }: { props: unknown }) {
  const v = useValid("SourceCitation", props);
  if (!v.success) return <Fallback name="sources" />;
  const p = v.data;
  // One entry per page, with its sections listed (the same page cited three times reads as noise).
  const pages: { doc_id: string; title: string; sections: string[]; note: string }[] = [];
  for (const s of p.sources) {
    const page = pages.find((x) => x.doc_id === s.doc_id);
    if (page) { if (!page.sections.includes(s.section)) page.sections.push(s.section); }
    else pages.push({ doc_id: s.doc_id, title: s.title, sections: [s.section], note: s.note || "" });
  }
  const current = pages.filter((x) => !x.note);
  const named = (current.length ? current : pages).map((x) => x.title).join(", ");
  // Requirement 4: the source is always named; the detail opens only if the traveller wants it.
  return (
    <details className="sources-pill" data-testid="source-citation">
      <summary><span className="sources-dot" />Source{pages.length > 1 ? "s" : ""}: <span className="sources-names">{named}</span></summary>
      <ul className="sources">
        {pages.map((x) => (
          <li key={x.doc_id} className={x.note ? "older" : undefined}><span className="ref">{x.doc_id}</span>
            <span>{x.title} <span className="cc-muted">· {x.sections.join(", ")}</span>{x.note && <span className="src-note">{x.note}</span>}</span></li>
        ))}
      </ul>
    </details>
  );
}

export const renderers = {
  PriceBreakdown, BookingForm, SpecialistHandoff, EnquiryConfirmation, TourCard, ItineraryDay, TravellerPicker,
  SourceCitation, TourShelf,
};
