"use client";

import * as React from "react";
import { Command as CommandPrimitive } from "cmdk";
import { plannerStyles } from "../plannerStyles";
import { cn } from "../../lib/utils";
import { InputGroup, InputGroupAddon, InputGroupInput } from "./InputGroup";
import { SearchIcon } from "lucide-react";

function Command({
  className,
  ...props
}: React.ComponentProps<typeof CommandPrimitive>) {
  return (
    <CommandPrimitive
      data-slot="command"
      className={cn(
        "flex h-full w-full flex-col overflow-hidden rounded-md bg-popover text-popover-foreground",
        className,
      )}
      {...props}
    />
  );
}

function CommandInput({
  className,
  id,
  expanded,
  ...props
}: React.ComponentProps<typeof CommandPrimitive.Input> & {
  expanded: boolean;
}) {
  return (
    <InputGroup className={cn(plannerStyles.field, "focus-within:outline-2 focus-within:outline-offset-1 focus-within:outline-(--blue)")}>
      <InputGroupAddon className="p-0">
        <SearchIcon className="size-4 shrink-0" />
      </InputGroupAddon>
      <CommandPrimitive.Input
        asChild
        data-slot="command-input"
        className={cn(
          "flex h-10 w-full rounded-md bg-transparent py-3 text-sm outline-hidden placeholder:text-muted-foreground disabled:cursor-not-allowed disabled:opacity-50",
          className,
        )}
        {...props}
      >
        <InputGroupInput
          className="h-auto min-h-[41px] rounded-none p-0! text-[15px] text-(--ink) placeholder:text-(--muted) focus-visible:outline-none! max-[700px]:text-base"
          id={id}
          aria-labelledby={id + "-label"}
          aria-expanded={expanded}
          {...(expanded ? {} : { "aria-controls": undefined })}
        />
      </CommandPrimitive.Input>
    </InputGroup>
  );
}

function CommandList({
  className,
  ...props
}: React.ComponentProps<typeof CommandPrimitive.List>) {
  return (
    <CommandPrimitive.List
      data-slot="command-list"
      className={cn(
        "max-h-[300px] scroll-py-1 overflow-x-hidden overflow-y-auto",
        className,
      )}
      {...props}
    />
  );
}

function CommandItem({
  className,
  ...props
}: React.ComponentProps<typeof CommandPrimitive.Item>) {
  return (
    <CommandPrimitive.Item
      data-slot="command-item"
      className={cn(
        "relative flex cursor-default items-center gap-2 rounded-sm px-2 py-1.5 text-sm outline-hidden select-none data-[disabled=true]:pointer-events-none data-[disabled=true]:opacity-50 data-[selected=true]:bg-accent data-[selected=true]:text-accent-foreground [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4 [&_svg:not([class*='text-'])]:text-muted-foreground",
        className,
      )}
      {...props}
    />
  );
}

export { Command, CommandInput, CommandList, CommandItem };
