import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "ReMind | Memory Care",
  description: "A caregiver station for resident activity, memory care, and care coordination.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
