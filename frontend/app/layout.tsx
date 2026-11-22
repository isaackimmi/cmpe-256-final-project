import type { ReactNode } from "react";
import Providers from "./Providers";

export const metadata = {
  title: "TripWorld | Explore",
  description: "Explore a destination through places you already love.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
