"use client";

import { useId, useRef, useState } from "react";
import { LoaderCircle, Search } from "lucide-react";
import { Input } from "./ui/input";
import { Button } from "./ui/button";

type Option = { id: string; name: string };

type Props<T extends Option> = {
  label: string;
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
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const expanded = open && Boolean(text.trim());
  const optionsId = id + "-options";

  // The action button can disappear when the query succeeds or reaches its final page.
  function runSearchAction(action: () => void) {
    input.current?.focus({ preventScroll: true });
    action();
  }

  function choose(item: T) {
    onSelect(item);
    setText("");
    setOpen(false);
    setActive(-1);
  }

  return (
    <div
      className="search-field"
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false);
      }}
    >
      <label htmlFor={id}>{props.label}</label>
      <div className="input-wrap">
        <Search size={17} aria-hidden />
        <Input
          ref={input}
          id={id}
          autoComplete="off"
          role="combobox"
          aria-autocomplete="list"
          aria-controls={expanded ? optionsId : undefined}
          aria-expanded={expanded}
          aria-activedescendant={
            expanded && items[active] ? id + "-" + active : undefined
          }
          value={text}
          placeholder={props.placeholder}
          onFocus={() => setOpen(true)}
          onChange={(event) => {
            setText(event.target.value);
            setActive(-1);
            setOpen(true);
          }}
          onKeyDown={(event) => {
            if (event.key === "Escape") {
              setOpen(false);
              return;
            }
            if (event.key === "ArrowDown" || event.key === "ArrowUp") {
              event.preventDefault();
              setOpen(true);
              const next =
                event.key === "ArrowDown"
                  ? Math.min(active + 1, items.length - 1)
                  : Math.max(0, active - 1);
              setActive(next);
              document
                .getElementById(id + "-" + next)
                ?.scrollIntoView({ block: "nearest" });
            } else if (expanded && event.key === "Enter" && items[active]) {
              event.preventDefault();
              choose(items[active]);
            }
          }}
        />
      </div>
      {expanded && (
        <div className="dropdown">
          <ul id={optionsId} role="listbox" aria-label={props.label}>
            {items.map((item, index) => (
              <li
                key={item.id}
                id={id + "-" + index}
                role="option"
                aria-selected={index === active}
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => choose(item)}
              >
                <span>{item.name}</span>
                {detail && <small>{detail(item)}</small>}
              </li>
            ))}
          </ul>
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
          {props.hasMore && (
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
    </div>
  );
}
