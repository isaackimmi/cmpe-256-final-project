import type { ReactNode } from "react";

export function Badge({ children }: { children: ReactNode }) {
  return (
    <span className="rounded-full bg-(--tint) px-2 py-1 text-xs text-(--blue)">
      {children}
    </span>
  );
}
