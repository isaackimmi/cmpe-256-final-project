"use client";

import { useId, useRef } from "react";
import { LoaderCircle } from "lucide-react";
import { Command, CommandInput, CommandList, CommandItem } from "./ui/Command";
import { Label } from "./ui/Label";
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

  // The action button can disappear when the query succeeds or reaches its final page.
  function runSearchAction(action: () => void) {
    input.current?.focus({ preventScroll: true });
    action();
  }

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
        htmlFor={id}
      >
        {props.label}
      </Label>
      <CommandInput
        autoFocus={props.autoFocus}
        ref={input}
        id={id}
        aria-label={props.label}
        aria-expanded={expanded}
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
          {props.failed ? (
            <div className="dropdown-note" role="status">
              Search failed.{" "}
              <Button
                variant="ghost"
                onClick={() => runSearchAction(props.retry)}
              >
                Try again
              </Button>
            </div>
          ) : props.loading ? (
            <div className="dropdown-note" role="status">
              <LoaderCircle className="spin" size={14} /> Searching…
            </div>
          ) : (
            !items.length && (
              <div className="dropdown-note" role="status">
                No matches.
              </div>
            )
          )}
          {props.hasMore && !props.failed && (
            <Button
              variant="ghost"
              className="more"
              disabled={props.loadingMore}
              onClick={() => runSearchAction(props.loadMore)}
            >
              {props.loadingMore ? "Loading…" : "Load more"}
            </Button>
          )}
        </div>
      )}
    </Command>
  );
}
