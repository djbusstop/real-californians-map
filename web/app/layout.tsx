import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Where Real Californians Live",
  description: "This isn't your grandma's census data map.",
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
