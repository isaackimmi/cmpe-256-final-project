"use client";

import * as Primitive from "@radix-ui/react-toggle-group";
import type { ComponentProps } from "react";

export const ToggleGroup = Primitive.Root;
export function ToggleGroupItem(props: ComponentProps<typeof Primitive.Item>) {
  return (
    <Primitive.Item
      className="rounded-lg border border-(--edge) px-3 py-1.5 text-sm data-[state=on]:bg-(--tint) data-[state=on]:text-(--blue) disabled:opacity-50"
      {...props}
    />
  );
}
