"use client";

import { useState } from "react";
import { ArrowRight, MapPin, X } from "lucide-react";
import { useDestinationSearch, usePlaceSearch } from "../hooks/use-search";
import type { Destination, Place } from "../lib/types";
import { SearchField } from "./search-field";
import { Button } from "./ui/button";

type Props = {
  visited: Place[];
  destination: Destination | null;
  setVisited: (places: Place[]) => void;
  setDestination: (destination: Destination | null) => void;
  submit: () => void;
};

export function TripSetup({
  visited,
  destination,
  setVisited,
  setDestination,
  submit,
}: Props) {
  const [placeText, setPlaceText] = useState("");
  const [destinationText, setDestinationText] = useState("");
  const places = usePlaceSearch(placeText);
  const destinations = useDestinationSearch(destinationText);
  const matches = places.data?.pages.flatMap((page) => page.items) ?? [];

  return (
    <section className="panel-content enter">
      <div className="heading">
        <h1>Explore a destination</h1>
        <p>Start with places you’ve visited to find where to go next.</p>
      </div>
      <SearchField<Place>
        label="Past places"
        placeholder="Search past places, e.g. Demo Park"
        text={placeText}
        setText={setPlaceText}
        items={matches.filter(
          (place) => !visited.some((v) => v.id === place.id),
        )}
        detail={(place) => place.tripworld_region_id}
        loading={
          places.isPending || (places.isFetching && !places.isFetchingNextPage)
        }
        failed={places.isError}
        retry={() => places.refetch()}
        hasMore={places.hasNextPage}
        loadingMore={places.isFetchingNextPage}
        loadMore={() => places.fetchNextPage()}
        onSelect={(place) => setVisited([...visited, place])}
      />
      {visited.length > 0 && (
        <ul className="chips">
          {visited.map((place) => (
            <li key={place.id}>
              <span>{place.name}</span>
              <button
                type="button"
                aria-label={`Remove ${place.name}`}
                onClick={() =>
                  setVisited(visited.filter((item) => item.id !== place.id))
                }
              >
                <X size={14} />
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="field-gap">
        {destination ? (
          <>
            <span className="field-label">Destination</span>
            <div className="chosen">
              <MapPin size={17} />
              <strong>{destination.name}</strong>
              <Button
                variant="ghost"
                aria-label="Change destination"
                onClick={() => setDestination(null)}
              >
                <X size={16} />
              </Button>
            </div>
          </>
        ) : (
          <SearchField<Destination>
            label="Destination"
            placeholder="Search a region, e.g. Kyoto"
            text={destinationText}
            setText={setDestinationText}
            items={destinations.data?.pages.flatMap((page) => page.items) ?? []}
            loading={
              destinations.isPending ||
              (destinations.isFetching && !destinations.isFetchingNextPage)
            }
            failed={destinations.isError}
            retry={() => destinations.refetch()}
            hasMore={destinations.hasNextPage}
            loadingMore={destinations.isFetchingNextPage}
            loadMore={() => destinations.fetchNextPage()}
            onSelect={setDestination}
          />
        )}
      </div>
      <Button
        className="find"
        disabled={!visited.length || !destination}
        onClick={submit}
      >
        Find places <ArrowRight size={17} />
      </Button>
    </section>
  );
}
