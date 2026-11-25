// Mira's A2UI catalog: zod prop schemas (the client-side twin of mira/ui/catalog.py).
// Fixed-schema components bind their values to the data model ({ path: "/field" }), so their
// props accept a literal OR a binding (Dynamic* schemas). Dynamic-schema components take literals.
// Every renderer re-validates the RESOLVED props with the `resolved` schemas below before drawing.
import { DynamicBooleanSchema, DynamicStringListSchema, DynamicStringSchema } from "@copilotkit/a2ui-renderer";
import { z } from "zod";

export const CATALOG_ID = "https://ceylon-compass.example/a2ui/mira-catalog/v1";

const Accent = z.enum(["teal", "leaf", "sun", "sky", "coral"]);
const DStr = DynamicStringSchema;
const DOptStr = DynamicStringSchema.nullable().optional();

// ---------- Resolved shapes (what renderers draw; mirrors the Pydantic models exactly) ----------
const TourCardSchema = z.object({
  accent: Accent, tour_id: z.string(), title: z.string(), category: z.string(), duration: z.string(),
  places: z.array(z.string()).max(10), summary: z.string(), priceable: z.boolean(),
  image: z.literal("placeholder"), source_ref: z.string(),
}).strict();

export const resolved = {
  PriceBreakdown: z.object({
    accent: Accent, quote_ref: z.string(), tour_id: z.string(), tour_title: z.string(),
    start_date: z.string(), end_date: z.string(), duration: z.string(), travellers_summary: z.string(),
    currency: z.literal("USD"), price_usd: z.string().regex(/^\d+(\.\d+)?$/),
    deposit_usd: z.string().regex(/^\d+(\.\d+)?$/), balance_usd: z.string().regex(/^\d+(\.\d+)?$/),
    balance_due_date: z.string().nullable().optional(), pay_in_full: z.boolean(),
    inclusions: z.array(z.string()).max(12),
  }).strict(),
  BookingForm: z.object({
    accent: Accent, quote_ref: z.string(), tour_title: z.string(), price_usd: z.string(),
    deposit_usd: z.string(), pay_in_full: z.boolean(), consent_text: z.string(),
  }).strict(),
  SpecialistHandoff: z.object({
    accent: Accent, title: z.string(), reason_text: z.string(), tour_title: z.string().nullable().optional(),
    flag_ref: z.string().nullable().optional(), enquiry_ref: z.string().nullable().optional(), cta_label: z.string(),
  }).strict(),
  EnquiryConfirmation: z.object({
    accent: Accent, enquiry_ref: z.string(), summary: z.string(), next_steps: z.array(z.string()).max(5),
  }).strict(),
  TourCard: TourCardSchema,
  ItineraryDay: z.object({
    accent: Accent, tour_id: z.string(), day_number: z.number().int().min(1).max(30), title: z.string(),
    description: z.string(), meals: z.array(z.string()).max(4), accommodation: z.string().nullable().optional(),
    entrance: z.array(z.string()).max(10), source_ref: z.string(),
  }).strict(),
  TravellerPicker: z.object({
    accent: Accent, prompt: z.string(), adults_default: z.number().int().min(1).max(20),
    child_ages_default: z.array(z.number().int().min(0).max(17)).max(19), max_group: z.number().int().min(1).max(20),
  }).strict(),
  TourShelf: z.object({
    title: z.string(),
    tours: z.array(TourCardSchema).min(2).max(4),
  }).strict(),
  SourceCitation: z.object({
    accent: Accent,
    sources: z.array(z.object({ passage_id: z.string(), doc_id: z.string(), title: z.string(), section: z.string() }).strict())
      .min(1).max(8),
  }).strict(),
};

// ---------- Catalog definitions (what the A2UI renderer accepts on the wire) ----------
export const definitions = {
  PriceBreakdown: {
    description: "Fixed schema. The confirmed price from the pricing engine. Values bound to the data model.",
    props: z.object({
      accent: Accent, quote_ref: DStr, tour_id: DStr, tour_title: DStr, start_date: DStr, end_date: DStr,
      duration: DStr, travellers_summary: DStr, currency: DStr, price_usd: DStr, deposit_usd: DStr,
      balance_usd: DStr, balance_due_date: DOptStr, pay_in_full: DynamicBooleanSchema,
      inclusions: DynamicStringListSchema,
    }),
  },
  BookingForm: {
    description: "Fixed schema. Booking form for a quote.",
    props: z.object({
      accent: Accent, quote_ref: DStr, tour_title: DStr, price_usd: DStr, deposit_usd: DStr,
      pay_in_full: DynamicBooleanSchema, consent_text: DStr,
    }),
  },
  SpecialistHandoff: {
    description: "Fixed schema. No price: a specialist will confirm.",
    props: z.object({
      accent: Accent, title: DStr, reason_text: DStr, tour_title: DOptStr, flag_ref: DOptStr,
      enquiry_ref: DOptStr, cta_label: DStr,
    }),
  },
  EnquiryConfirmation: {
    description: "Fixed schema. Confirms a saved enquiry.",
    props: z.object({ accent: Accent, enquiry_ref: DStr, summary: DStr, next_steps: DynamicStringListSchema }),
  },
  TourCard: { description: "Dynamic. A tour from our content (never shows a price).", props: resolved.TourCard },
  ItineraryDay: { description: "Dynamic. One day of a tour itinerary from content.", props: resolved.ItineraryDay },
  TravellerPicker: { description: "Dynamic. Pick adults and children's ages.", props: resolved.TravellerPicker },
  SourceCitation: { description: "Dynamic. The content sources an answer used.", props: resolved.SourceCitation },
  TourShelf: { description: "Dynamic. Two to four tour cards in one row.", props: resolved.TourShelf },
};

export type ComponentName = keyof typeof resolved;
