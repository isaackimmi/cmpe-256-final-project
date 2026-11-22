"use client";

import { useRef, useState } from "react";
import { ArrowRight, ChevronDown, MapPin, X } from "lucide-react";
import { useDestinationSearch, usePlaceSearch } from "../hooks/useSearch";
import type { Destination, Place } from "../lib/types";
import { cn } from "../lib/utils";
import { plannerStyles } from "./plannerStyles";
import { SearchField } from "./SearchField";
import { ScrollArea } from "./ui/ScrollArea";
import { Button } from "./ui/Button";
import { plannerStyles } from "./plannerStyles";

type Props = {
  visited: Place[];
  destination: Destination | null;
  setVisited: (places: Place[]) => void;
  setDestination: (destination: Destination) => void;
  onInteract: () => void;
  submit: () => void;
  autoFocusSubmit: boolean;
};

export function TripSetup({
  visited,
  destination,
  setVisited,
  setDestination,
  onInteract,
  submit,
  autoFocusSubmit,
}: Props) {
  const [placeText, setPlaceText] = useState("");
  const [destinationText, setDestinationText] = useState("");
  const [editingDestination, setEditingDestination] = useState(false);
  const [placesOpen, setPlacesOpen] = useState(false);
  const [destinationsOpen, setDestinationsOpen] = useState(false);
  const places = usePlaceSearch(placeText, placesOpen);
  const destinations = useDestinationSearch(destinationText, destinationsOpen);
  const matches = places.data?.pages.flatMap((page) => page.items) ?? [];

  const restoreDestinationFocus = useRef(false);

  function closeDestinationEditor() {
    restoreDestinationFocus.current = true;
    setDestinationText("");
    setDestinationsOpen(false);
    setEditingDestination(false);
  }

  return (
    <section className="enter" onFocusCapture={onInteract}>
      <h1>Plan your visit</h1>
      {destination && !editingDestination ? (
        <>
          <span className={plannerStyles.label}>Destination</span>
          <Button
            variant="ghost"
            ref={(button) => {
              if (button && restoreDestinationFocus.current) {
                restoreDestinationFocus.current = false;
                button.focus({ preventScroll: true });
              }
            }}
            className={cn(plannerStyles.field, "w-full text-left text-[15px] font-normal whitespace-normal")}
            aria-label={`Change destination: ${destination.name}`}
            onClick={() => setEditingDestination(true)}
          >
            <MapPin size={18} />
            <span className="min-w-0 flex-1 wrap-anywhere text-(--ink)">
              {[destination.name, destination.country]
                .filter(Boolean)
                .join(", ")}
            </span>
            <ChevronDown size={16} />
          </Button>
        </>
      ) : (
        <div className="relative">
          <SearchField<Destination>
            label="Destination"
            expanded={destinationsOpen}
            onOpenChange={setDestinationsOpen}
            placeholder="Search cities or regions"
            autoFocus={editingDestination}
            text={destinationText}
            setText={setDestinationText}
            onSelect={(item) => {
              setDestination(item);
              closeDestinationEditor();
            }}
            items={destinations.data?.pages.flatMap((page) => page.items) ?? []}
            detail={(city) => city.country ?? ""}
            query={destinations}
          />
          {editingDestination && (
            <Button
              variant="ghost"
              className="absolute -top-1 right-0 h-[26px] text-[13px] text-(--blue)"
              onClick={closeDestinationEditor}
            >
              Cancel
            </Button>
          )}
        </div>
      )}
      <section className={plannerStyles.history}>
        <h2>Previously visited destinations</h2>
        <p>Add the specific places you visited on earlier trips.</p>
        <SearchField<Place>
          label="Search previously visited places"
          expanded={placesOpen}
          onOpenChange={setPlacesOpen}
          hideLabel
          placeholder="Search past places"
          text={placeText}
          setText={setPlaceText}
          items={matches.filter(
            (place) => !visited.some((v) => v.id === place.id),
          )}
          detail={(place) => place.locality ?? ""}
          onSelect={(place) => setVisited([...visited, place])}
          query={places}
        />
        <ScrollArea className={plannerStyles.visits}>
          <ul aria-label="Selected past places" className="divide-y divide-(--edge)">
            {visited.map((place) => (
              <li key={place.id} className="flex w-full items-center gap-[11px] py-[9px] text-left">
                <span className="grid size-8 shrink-0 place-items-center rounded-[10px] bg-(--tint) text-(--blue)">
                  <MapPin size={17} />
                </span>
                <div className="min-w-0 wrap-anywhere">
                  <strong className="block text-sm leading-[1.4] font-[630]">{place.name}</strong>
                  {place.locality && <small className="mt-px block text-xs leading-[1.4] text-(--muted)">{place.locality}</small>}
                </div>
                <Button
                  variant="ghost"
                  size="icon"
                  className="ml-auto size-[30px] rounded-full text-(--muted) hover:bg-(--tint)"
                  aria-label={`Remove ${place.name}`}
                  onClick={() =>
                    setVisited(visited.filter((item) => item.id !== place.id))
                  }
                >
                  <X size={15} />
                </Button>
              </li>
            ))}
          </ul>
        </ScrollArea>
      </section>
      <Button
        className={plannerStyles.primaryButton}
        autoFocus={autoFocusSubmit}
        disabled={!visited.length || !destination || editingDestination}
        onClick={submit}
      >
        Find places <ArrowRight size={18} />
      </Button>
    </section>
  );
}
