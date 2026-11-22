// Load the brand pack from the dataset (read-only) and turn it into CSS variables.
// Server-only: runs in the root layout.
import fs from "node:fs";
import path from "node:path";

type BrandPack = {
  name: string;
  assistant_name: string;
  colors: {
    black: string; white: string; orange: string;
    accents: Record<string, string>;
    surface: string; text: string; muted_text: string; border: string;
  };
  typography: { font_family: string; scale_px: Record<string, number>; weights: Record<string, number> };
  spacing_px: number[];
  radius_px: Record<string, number>;
  cards: { max_width_px: number };
};

export function loadBrand(): BrandPack {
  const file = path.join(process.cwd(), "..", "data", "ceylon-compass-dataset", "brand", "brand_pack.json");
  return JSON.parse(fs.readFileSync(file, "utf-8")) as BrandPack;
}

export function brandCss(b: BrandPack): string {
  const vars: Record<string, string | number> = {
    "--cc-black": b.colors.black,
    "--cc-white": b.colors.white,
    "--cc-orange": b.colors.orange,
    "--cc-surface": b.colors.surface,
    "--cc-text": b.colors.text,
    "--cc-muted": b.colors.muted_text,
    "--cc-border": b.colors.border,
    "--cc-font": b.typography.font_family,
    "--cc-radius-card": `${b.radius_px.card}px`,
    "--cc-radius-button": `${b.radius_px.button}px`,
    "--cc-radius-input": `${b.radius_px.input}px`,
    "--cc-card-max": `${b.cards.max_width_px}px`,
  };
  for (const [name, hex] of Object.entries(b.colors.accents)) vars[`--cc-${name}`] = hex;
  for (const [name, px] of Object.entries(b.typography.scale_px)) vars[`--cc-text-${name}`] = `${px}px`;
  for (const [name, w] of Object.entries(b.typography.weights)) vars[`--cc-weight-${name}`] = w;
  b.spacing_px.forEach((px, i) => (vars[`--cc-space-${i + 1}`] = `${px}px`));
  return `:root{${Object.entries(vars).map(([k, v]) => `${k}:${v}`).join(";")}}`;
}
