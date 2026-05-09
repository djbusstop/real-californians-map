import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Where Real Californians Live",
  description:
    "Subcultures of California, mapped from ACS PUMS via configurable proxy vectors.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
