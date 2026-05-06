import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Turfify",
  description: "Turf Management & Booking Platform",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-white text-neutral-900 antialiased">{children}</body>
    </html>
  );
}
