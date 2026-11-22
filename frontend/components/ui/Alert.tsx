import type { ReactNode } from "react";

export function Alert({ children }: { children: ReactNode }) {
  return (
    <div role="alert" className="rounded-lg border border-(--edge) p-3 text-sm">
      {children}
    </div>
  );
}
