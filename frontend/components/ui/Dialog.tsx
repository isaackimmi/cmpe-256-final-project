"use client";

import * as Primitive from "@radix-ui/react-dialog";
import type { ComponentProps } from "react";

export const Dialog = Primitive.Root;
export const DialogTrigger = Primitive.Trigger;
export const DialogClose = Primitive.Close;
export const DialogTitle = Primitive.Title;
export const DialogDescription = Primitive.Description;

export function DialogContent(props: ComponentProps<typeof Primitive.Content>) {
  return (
    <Primitive.Portal>
      <Primitive.Overlay className="fixed inset-0 z-40 bg-black/40" />
      <Primitive.Content
        className="glass-surface fixed top-1/2 left-1/2 z-50 grid max-h-[92dvh] w-[min(38rem,95vw)] -translate-1/2 grid-rows-[auto_minmax(0,1fr)_auto] rounded-2xl p-5 text-(--ink)"
        {...props}
      />
    </Primitive.Portal>
  );
}
