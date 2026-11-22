"use client";

import { useEffect, useRef } from "react";
import { ArrowLeft } from "lucide-react";
import type { Recommendation } from "../lib/types";
import { Skeleton } from "./ui/Skeleton";
import { ScrollArea } from "./ui/ScrollArea";
import { Button } from "./ui/Button";

type Props = {
  destination: string;
  results: Recommendation[];
  selected?: Recommendation;
  onSelect: (id: string) => void;
  onEdit: () => void;
  loading: boolean;
  failed: boolean;
  retry: () => void;
};

export function TripResults({
  destination,
  results,
  selected,
  onSelect,
  onEdit,
  loading,
  failed,
  retry,
}: Props) {
  const title = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    title.current?.focus({ preventScroll: true });
  }, []);

  return (
    <section className="enter">
      <Button variant="ghost" className="edit" onClick={onEdit}>
        <ArrowLeft size={16} /> Edit trip
      </Button>
      <h1 ref={title} tabIndex={-1}>
        Recommended places
      </h1>
      <div className="subtitle" role="status">
        {loading ? (
          <>
            <span className="sr-only">{results.length ? "Updating places in this map area…" : "Finding places…"}</span>
            <Skeleton aria-hidden="true" className="loading-placeholder my-1 h-4 w-36" />
          </>
        ) : <>For your visit to {destination}</>}
      </div>
      {failed && (
        <div role="alert" className="notice">
          {results.length
            ? "Couldn’t update this map area. Showing the last available places."
            : "Couldn’t load recommendations."}{" "}
          <Button variant="ghost" onClick={retry}>
            Try again
          </Button>
        </div>
      )}
      {!failed && !loading && !results.length && (
        <div role="status" className="notice">
          No matching places in this area.
        </div>
      )}
      <ScrollArea className="rank-scroll">
        <ol className="rank-list" aria-busy={loading}>
          {loading &&
            !results.length &&
            [0, 1, 2, 3].map((row) => (
              <li key={row} aria-hidden="true">
                <div className="flex min-h-12 items-center gap-[11px] p-2">
                  <Skeleton className="loading-placeholder size-[25px] rounded-full" />
                  <div className="grid flex-1 gap-1.5">
                    <Skeleton className="loading-placeholder h-3.5 w-3/5" />
                    <Skeleton className="loading-placeholder h-3 w-2/5" />
                  </div>
                </div>
              </li>
            ))}
          {results.map((place) => (
            <li key={place.id}>
              <Button
                variant="ghost"
                className="h-auto justify-start whitespace-normal"
                aria-pressed={selected?.id === place.id}
                onClick={() => onSelect(place.id)}
              >
                <span className="rank">{place.rank}</span>
                <span>
                  <strong>{place.name}</strong>
                  <small>
                    {[place.category, place.locality]
                      .filter(Boolean)
                      .join(" · ")}
                  </small>
                </span>
              </Button>
            </li>
          ))}
        </ol>
      </ScrollArea>
    </section>
  );
}
