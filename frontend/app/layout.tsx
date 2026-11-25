import type { Metadata, Viewport } from "next";
import { Inter } from "next/font/google";
import "@copilotkit/react-core/v2/styles.css";
import "./globals.css";
import { brandCss, loadBrand } from "@/lib/brand";

// The brand pack's typeface. Self-hosted by Next.js at build time (no request to Google from the browser).
const inter = Inter({ subsets: ["latin"], weight: ["400", "600", "700"], variable: "--cc-font-inter", display: "swap" });

export const metadata: Metadata = {
  title: "Mira · Ceylon Compass Holidays",
  description: "Plan and price a Sri Lanka trip in a conversation.",
};

export const viewport: Viewport = { width: "device-width", initialScale: 1, themeColor: "#FFFFFF" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  const brand = loadBrand();
  return (
    <html lang="en" className={inter.variable}>
      <head>
        <style dangerouslySetInnerHTML={{ __html: brandCss(brand) }} />
      </head>
      <body>{children}</body>
    </html>
  );
}
