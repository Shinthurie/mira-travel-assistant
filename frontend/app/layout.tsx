import type { Metadata, Viewport } from "next";
import "@copilotkit/react-core/v2/styles.css";
import "./globals.css";
import { brandCss, loadBrand } from "@/lib/brand";

export const metadata: Metadata = {
  title: "Mira · Ceylon Compass Holidays",
  description: "Plan and price a Sri Lanka trip in a conversation.",
};

export const viewport: Viewport = { width: "device-width", initialScale: 1 };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  const brand = loadBrand();
  return (
    <html lang="en">
      <head>
        <style dangerouslySetInnerHTML={{ __html: brandCss(brand) }} />
      </head>
      <body>{children}</body>
    </html>
  );
}
