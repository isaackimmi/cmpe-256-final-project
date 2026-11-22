"use client";

import { useEffect, useId, useRef } from "react";
import type { UseInfiniteQueryResult } from "@tanstack/react-query";
import { SEARCH_TERM_MAX_LENGTH } from "../hooks/useSearch";
import { plannerStyles } from "./plannerStyles";
import { Skeleton } from "./ui/Skeleton";
import { Command, CommandInput, CommandList, CommandItem } from "./ui/Command";
import { Label } from "./ui/Label";
import { ScrollArea } from "./ui/ScrollArea";
import { Button } from "./ui/Button";

type Option = { id: string; name: string };

type Props<T extends Option> = {
  label: string;
  hideLabel?: boolean;
  autoFocus?: boolean;
  expanded: boolean;
  onOpenChange: (open: boolean) => void;
  placeholder: string;
  text: string;
  setText: (text: string) => void;
  items: T[];
  detail?: (item: T) => string;
  onSelect: (item: T) => void;
  query: UseInfiniteQueryResult;
};

export function SearchField<T extends Option>(props: Props<T>) {
  const { items, text, setText, onSelect, detail } = props;
  const id = useId();
  const input = useRef<HTMLInputElement>(null);
  const { expanded, onOpenChange: setOpen } = props;

  const sentinel = useRef<HTMLDivElement>(null);
  const { query } = props;
  const { fetchNextPage } = query;
  const canLoadMore = expanded && query.hasNextPage && query.fetchStatus === "idle" && !query.isError;

  useEffect(() => {
    const target = sentinel.current;
    if (!canLoadMore || !target) return;
    const viewport = target.closest("[data-slot='scroll-area-viewport']");
    const observer = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) {
        observer.disconnect();
        fetchNextPage();
      }
    }, { root: viewport });
    observer.observe(target);
    return () => observer.disconnect();
  }, [canLoadMore, fetchNextPage]);

  function choose(item: T) {
    onSelect(item);
    setText("");
    setOpen(false);
  }

  return (
    <Command
      label={props.label}
      shouldFilter={false}
      className="relative h-auto overflow-visible [--skeleton-fill:#d1d5db]"
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false);
      }}
    >
      <Label
        className={props.hideLabel ? "sr-only" : plannerStyles.label}
        id={id + "-label"}
        htmlFor={id}
      >
        {props.label}
      </Label>
      <CommandInput
        maxLength={SEARCH_TERM_MAX_LENGTH}
        autoFocus={props.autoFocus}
        ref={input}
        id={id}
        aria-label={props.label}
        expanded={expanded}
        value={text}
        placeholder={props.placeholder}
        onValueChange={(value) => {
          setText(value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onClick={() => setOpen(true)}
        onKeyDown={(event) => {
          if (event.key === "Escape") {
            setOpen(false);
            event.stopPropagation();
          }
          if (event.key === "ArrowDown" || event.key === "ArrowUp")
            setOpen(true);
        }}
      />
      {expanded && (
        <div className="absolute inset-x-0 top-full z-3 mt-[5px] overflow-hidden rounded-[10px] border border-(--edge) bg-(--surface) shadow-[0_6px_18px_#172e3520]">
          <ScrollArea viewportClassName="max-h-[min(186px,29svh)]" thumbClassName="mx-auto flex-none basis-[3px]">
            <CommandList label={props.label} className="max-h-none overflow-visible">
              {items.map((item) => (
                <CommandItem
                  key={item.id}
                  className="relative block cursor-pointer px-2.5 py-[9px] pr-[30px] text-sm leading-[1.4] font-[630] hover:bg-(--tint) data-[selected=true]:bg-(--tint)"
                  value={item.id}
                  onMouseDown={(event) => event.preventDefault()}
                  onSelect={() => choose(item)}
                >
                  <span>{item.name}</span>
                  {detail && <small className="block text-xs leading-[1.4] font-normal text-(--muted)">{detail(item)}</small>}
                  <span aria-hidden="true" className="absolute top-1/2 right-[11px] -translate-y-1/2 text-base font-normal text-(--muted)">+</span>
                </CommandItem>
              ))}
            </CommandList>
            <div
              onKeyDown={(event) => {
                if (event.key === "Enter") event.stopPropagation();
              }}
            >
              {query.isPaused ? (
                <div className={plannerStyles.notice} role="status">
                  Search will resume when you’re online.
                </div>
              ) : query.isError && !query.isFetching ? (
                <div className={plannerStyles.notice} role="status">
                  Search failed.{" "}
                  <Button
                    variant="ghost"
                    onClick={() => {
                      input.current?.focus({ preventScroll: true });
                      if (query.isFetchNextPageError) fetchNextPage();
                      else query.refetch();
                    }}
                  >
                    Try again
                  </Button>
                </div>
              ) : query.isPending || query.isFetching ? (
                <div role="status">
                  <span className="sr-only">
                    {query.isFetchingNextPage ? "Loading more results…" : "Searching…"}
                  </span>
                  {[0, 1, 2].map((row) => (
                    <div key={row} aria-hidden="true" className="grid h-14 content-center gap-2 px-2.5">
                      <Skeleton className="h-3.5 w-3/5" />
                      <Skeleton className="h-3 w-1/3" />
                    </div>
                  ))}
                </div>
              ) : (
                !items.length && !query.hasNextPage && (
                  <div className={plannerStyles.notice} role="status">
                    No matches.
                  </div>
                )
              )}
              {canLoadMore && <div ref={sentinel} aria-hidden="true" className="h-px" />}
            </div>
          </ScrollArea>
        </div>
      )}
    </Command>
  );
}
