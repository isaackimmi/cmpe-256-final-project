import type { ReactNode } from "react";

export const metadata = { title: "TripWorld | CMPE 256" };

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
