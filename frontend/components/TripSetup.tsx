"use client";

import { useState } from "react";
import { ChevronDown, MapPin, X } from "lucide-react";
import { useDestinationSearch, usePlaceSearch } from "../hooks/useSearch";
import type { Destination, Place } from "../lib/types";
import { SearchField } from "./SearchField";
import { ScrollArea } from "./ui/ScrollArea";
import { Button } from "./ui/Button";

type Props = {
  visited: Place[];
  destination: Destination | null;
  setVisited: (places: Place[]) => void;
  setDestination: (destination: Destination) => void;
  onInteract: () => void;
};

export function TripSetup({
  visited,
  destination,
  setVisited,
  setDestination,
  onInteract,
}: Props) {
  const [placeText, setPlaceText] = useState("");
  const [destinationText, setDestinationText] = useState("");
  const [editingDestination, setEditingDestination] = useState(false);
  const [placesOpen, setPlacesOpen] = useState(false);
  const [destinationsOpen, setDestinationsOpen] = useState(false);
  const places = usePlaceSearch(placeText, placesOpen);
  const destinations = useDestinationSearch(destinationText, destinationsOpen);
  const matches = places.data?.pages.flatMap((page) => page.items) ?? [];

  function chooseDestination(item: Destination) {
    setDestination(item);
    setEditingDestination(false);
  }

  return (
    <section className="enter" onFocusCapture={onInteract}>
      <h1>Plan your visit</h1>
      {destination && !editingDestination ? (
        <>
          <span className="section-title">Destination</span>
          <Button
            variant="ghost"
            className="field chosen"
            aria-label={`Change destination: ${destination.name}`}
            onClick={() => setEditingDestination(true)}
          >
            <MapPin size={18} />
            <span>
              {[destination.name, destination.country]
                .filter(Boolean)
                .join(", ")}
            </span>
            <ChevronDown size={16} />
          </Button>
        </>
      ) : (
        <div className="destination-picker">
          <SearchField<Destination>
            label="Destination"
            expanded={destinationsOpen}
            onOpenChange={setDestinationsOpen}
            placeholder="Search cities or regions"
            autoFocus={editingDestination}
            text={destinationText}
            setText={setDestinationText}
            onSelect={chooseDestination}
            items={destinations.data?.pages.flatMap((page) => page.items) ?? []}
            detail={(city) => city.country ?? ""}
            loading={
              destinations.isPending ||
              (destinations.isFetching && !destinations.isFetchingNextPage)
            }
            failed={destinations.isError}
            retry={() =>
              destinations.isFetchNextPageError
                ? destinations.fetchNextPage()
                : destinations.refetch()
            }
            hasMore={destinations.hasNextPage}
            loadingMore={destinations.isFetchingNextPage}
            loadMore={() => destinations.fetchNextPage()}
          />
          {editingDestination && (
            <Button
              variant="ghost"
              className="cancel"
              onClick={() => setEditingDestination(false)}
            >
              Cancel
            </Button>
          )}
        </div>
      )}
      <section className="history-section">
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
          loading={
            places.isPending ||
            (places.isFetching && !places.isFetchingNextPage)
          }
          failed={places.isError}
          retry={() =>
            places.isFetchNextPageError
              ? places.fetchNextPage()
              : places.refetch()
          }
          hasMore={places.hasNextPage}
          loadingMore={places.isFetchingNextPage}
          loadMore={() => places.fetchNextPage()}
        />
        <ScrollArea className="visits">
          <ul aria-label="Selected past places">
            {visited.map((place) => (
              <li key={place.id}>
                <span className="visit-icon">
                  <MapPin size={17} />
                </span>
                <div>
                  <strong>{place.name}</strong>
                  {place.locality && <small>{place.locality}</small>}
                </div>
                <Button
                  variant="ghost"
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
    </section>
  );
}
