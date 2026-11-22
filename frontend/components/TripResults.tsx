"use client";

import { useEffect, useRef } from "react";
import { ArrowLeft, Crosshair } from "lucide-react";
import type { Recommendation } from "../lib/types";
import type { useRecommendations } from "../hooks/useRecommendations";
import { SkeletonRow } from "./SkeletonRow";
import { ScrollArea } from "./ui/ScrollArea";
import { Button } from "./ui/Button";
import { plannerStyles } from "./plannerStyles";

type Props = {
  itinerary: React.ReactNode;
  destination: string;
  recommendations: ReturnType<typeof useRecommendations>;
  selected?: Recommendation;
  onSelect: (id: string) => void;
  onEdit: () => void;
  resetBounds?: () => void;
};

export function TripResults({
  itinerary,
  destination,
  recommendations,
  selected,
  onSelect,
  onEdit,
  resetBounds,
}: Props) {
  const { data, isFetching, isPaused, isError, isSuccess, refetch } = recommendations;
  const results = data?.results ?? [];
  const title = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    title.current?.focus({ preventScroll: true });
  }, []);

  return (
    <section className="enter">
      <Button
        variant="ghost"
        className="mb-3.5 gap-[7px] p-0 text-[13px] font-semibold text-(--blue) has-[>svg]:px-0"
        onClick={onEdit}
      >
        <ArrowLeft size={16} /> Edit trip
      </Button>
      <h1 ref={title} tabIndex={-1} className="mb-[3px] text-[27px] leading-[1.1] font-[730] tracking-[-1.4px]">
        Recommended places
      </h1>
      <div className="mb-1.5 text-sm text-(--muted)" role="status">
        {isPaused
          ? "Recommendations will load when you’re back online."
          : isFetching && results.length > 0
            ? "Updating places in this map area…"
            : `For your visit to ${destination}`}
        {isFetching && !results.length && <span className="sr-only"> Finding places…</span>}
      </div>
      {itinerary}
      {resetBounds && (
        <Button variant="outline" className="mb-3 border-(--edge) text-(--blue)!" onClick={resetBounds}>
          <Crosshair size={14} /> Search whole destination
        </Button>
      )}
      {isError && (
        <div role="alert" className={plannerStyles.notice}>
          {results.length
            ? "Couldn’t update this map area. Showing the last available places."
            : "Couldn’t load recommendations."}{" "}
          <Button variant="ghost" onClick={() => refetch()}>
            Try again
          </Button>
        </div>
      )}
      {isSuccess && !isPaused && !isFetching && !results.length && (
        <div role="status" className={plannerStyles.notice}>
          No matching places in this area.
        </div>
      )}
      <ScrollArea viewportClassName="max-h-[min(15rem,38svh)]">
        <ol aria-label="Ranked recommendations" className="grid gap-1" aria-busy={isFetching}>
          {isFetching &&
            !results.length &&
            [0, 1, 2, 3].map((row) => (
              <li key={row} aria-hidden="true">
                <SkeletonRow
                  className="min-h-12 gap-[11px] p-2"
                  iconClassName="size-[25px] rounded-full"
                />
              </li>
            ))}
          {results.map((place) => (
            <li key={place.id}>
              <Button
                variant="ghost"
                className="group h-auto w-full justify-start gap-[11px] rounded-[10px] p-2 text-left whitespace-normal hover:bg-(--tint) aria-pressed:bg-(--tint) aria-pressed:text-(--blue)"
                aria-pressed={selected?.id === place.id}
                onClick={() => onSelect(place.id)}
              >
                <span className="grid size-[25px] shrink-0 place-items-center rounded-full border border-(--edge) text-xs font-bold group-aria-pressed:border-transparent group-aria-pressed:bg-[#0865db] group-aria-pressed:text-white">
                  {place.rank}
                </span>
                <span className="min-w-0 wrap-anywhere">
                  <strong className="block text-sm font-[630]">{place.name}</strong>
                  <small className="mt-px block text-xs font-normal text-(--muted)">
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
