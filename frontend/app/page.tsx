"use client";

import { useState } from "react";
import { Globe2, Moon, Sun } from "lucide-react";
import MapView from "../components/MapView";
import { TripResults } from "../components/TripResults";
import { TripSetup } from "../components/TripSetup";
import { Button } from "../components/ui/Button";
import { useRecommendations } from "../hooks/useRecommendations";
import { useTheme } from "../hooks/useTheme";
import type {
  Bounds,
  Destination,
  Place,
  RecommendationRequest,
} from "../lib/types";

export default function Home() {
  const { theme, toggle } = useTheme();
  const [visited, setVisited] = useState<Place[]>([]);
  const [destination, setDestination] = useState<Destination | null>(null);
  const [request, setRequest] = useState<RecommendationRequest | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [cameraRevision, setCameraRevision] = useState(0);
  const recommendations = useRecommendations(request);
  const results = recommendations.data?.results ?? [];

  function startTrip() {
    if (!destination || !visited.length) return;
    setSelectedId(null);
    setCameraRevision((revision) => revision + 1);
    setRequest({
      tripworld_region_id: destination.id,
      visited_place_ids: visited.map((place) => place.id),
    });
  }

  function changeBounds(bounds: Bounds) {
    setRequest((current) => current && { ...current, bounds });
  }

  return (
    <div className="planner">
      <header className="topbar">
        <div className="brand">
          <span className="brand-symbol">
            <Globe2 size={23} />
          </span>
          TripWorld
        </div>
        <Button
          variant="outline"
          className="theme-toggle"
          aria-label={`Use ${theme === "light" ? "dark" : "light"} theme`}
          onClick={toggle}
        >
          {theme === "light" ? <Moon size={17} /> : <Sun size={17} />}
        </Button>
      </header>
      <main className="workspace">
        <aside className="sidebar" aria-label="Trip planner">
          {request && destination ? (
            <TripResults
              destination={destination.name}
              results={results}
              selectedId={selectedId}
              onSelect={setSelectedId}
              onEdit={() => {
                setRequest(null);
                setSelectedId(null);
              }}
              resetBounds={request.bounds ? startTrip : undefined}
              loading={recommendations.isFetching}
              failed={recommendations.isError}
              retry={() => recommendations.refetch()}
              demo={recommendations.data?.model_version === "stub-v1"}
            />
          ) : (
            <TripSetup
              visited={visited}
              destination={destination}
              setVisited={setVisited}
              setDestination={setDestination}
              submit={startTrip}
            />
          )}
        </aside>
        <section className="map-region" aria-label="Recommendation map">
          <MapView
            cameraRevision={cameraRevision}
            isLoading={recommendations.isFetching}
            results={request ? results : []}
            destinationId={request?.tripworld_region_id ?? null}
            selectedId={selectedId}
            onSelect={setSelectedId}
            onBoundsChange={changeBounds}
            theme={theme}
          />
        </section>
      </main>
    </div>
  );
}
