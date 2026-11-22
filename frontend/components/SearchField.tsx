"use client";

import { useEffect, useId, useRef } from "react";
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
  loading: boolean;
  failed: boolean;
  retry: () => void;
  hasMore: boolean;
  loadingMore: boolean;
  loadMore: () => void;
};

export function SearchField<T extends Option>(props: Props<T>) {
  const { items, text, setText, onSelect, detail } = props;
  const id = useId();
  const input = useRef<HTMLInputElement>(null);
  const { expanded, onOpenChange: setOpen } = props;

  const sentinel = useRef<HTMLDivElement>(null);
  const { loadMore } = props;
  const canLoadMore = expanded && props.hasMore && !props.loading && !props.loadingMore && !props.failed;

  useEffect(() => {
    const target = sentinel.current;
    if (!canLoadMore || !target) return;
    const viewport = target.closest("[data-slot='scroll-area-viewport']");
    const observer = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) {
        observer.disconnect();
        loadMore();
      }
    }, { root: viewport });
    observer.observe(target);
    return () => observer.disconnect();
  }, [canLoadMore, loadMore]);

  function choose(item: T) {
    onSelect(item);
    setText("");
    setOpen(false);
  }

  return (
    <Command
      label={props.label}
      shouldFilter={false}
      className="search-field h-auto overflow-visible"
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false);
      }}
    >
      <Label
        className={props.hideLabel ? "sr-only" : "section-title"}
        id={id + "-label"}
        htmlFor={id}
      >
        {props.label}
      </Label>
      <CommandInput
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
        <div className="dropdown">
          <ScrollArea>
            <CommandList label={props.label} className="overflow-visible">
              {items.map((item) => (
                <CommandItem
                  key={item.id}
                  value={item.id}
                  onMouseDown={(event) => event.preventDefault()}
                  onSelect={() => choose(item)}
                >
                  <span>{item.name}</span>
                  {detail && <small>{detail(item)}</small>}
                </CommandItem>
              ))}
            </CommandList>
            <div
              onKeyDown={(event) => {
                if (event.key === "Enter") event.stopPropagation();
              }}
            >
              {props.failed ? (
                <div className="dropdown-note" role="status">
                  Search failed.{" "}
                  <Button
                    variant="ghost"
                    onClick={() => {
                      input.current?.focus({ preventScroll: true });
                      props.retry();
                    }}
                  >
                    Try again
                  </Button>
                </div>
              ) : props.loading || props.loadingMore ? (
                <div role="status">
                  <span className="sr-only">
                    {props.loadingMore ? "Loading more results…" : "Searching…"}
                  </span>
                  {[0, 1, 2].map((row) => (
                    <div key={row} aria-hidden="true" className="grid h-14 content-center gap-2 px-2.5">
                      <Skeleton className="loading-placeholder h-3.5 w-3/5" />
                      <Skeleton className="loading-placeholder h-3 w-1/3" />
                    </div>
                  ))}
                </div>
              ) : (
                !items.length && (
                  <div className="dropdown-note" role="status">
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
