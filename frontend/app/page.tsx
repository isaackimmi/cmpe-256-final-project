"use client";

import { lazy, Suspense, useState } from "react";
import { Compass, Moon, Sun } from "lucide-react";
import { PlannerLoading } from "../components/PlannerLoading";
import { TripResults } from "../components/TripResults";
import { TripSetup } from "../components/TripSetup";
import { Button } from "../components/ui/Button";
import { useDemoTrip } from "../hooks/useDemoTrip";
import { useRecommendations } from "../hooks/useRecommendations";
import { useTheme } from "../hooks/useTheme";
import type {
  Bounds,
  Destination,
  Place,
  RecommendationRequest,
} from "../lib/types";

const MapView = lazy(() => import("../components/MapView"));

type Trip = { destination: Destination | null; visited: Place[] };

export default function Home() {
  const { theme, toggle } = useTheme();
  const demo = useDemoTrip();
  const [editedTrip, setEditedTrip] = useState<Trip | null>(null);
  const trip = editedTrip ?? demo.data ?? { destination: null, visited: [] };
  const { destination, visited } = trip;
  const [request, setRequest] = useState<RecommendationRequest | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [cameraRevision, setCameraRevision] = useState(0);
  const recommendations = useRecommendations(request);
  const results = recommendations.data?.results ?? [];
  const selected =
    results.find((place) => place.id === selectedId) ?? results[0];

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
    <main className={`trip-design ${theme === "dark" ? "night" : "day"}`}>
      <header className="glass topbar">
        <div className="brand">
          <span className="brand-mark">
            <Compass size={26} />
          </span>
          TripWorld
        </div>
        <div className="bar-context">
          <span className="context-dot" />
          Explore
        </div>
        <Button
          variant="ghost"
          className="theme"
          aria-label={`Switch to ${theme === "light" ? "dark" : "light"} mode`}
          onClick={toggle}
        >
          {theme === "light" ? <Moon size={18} /> : <Sun size={18} />}
          <span>{theme === "light" ? "Dark mode" : "Light mode"}</span>
        </Button>
      </header>
      <section className="map-region" aria-label="Recommendation map">
        <Suspense
          fallback={
            <div className="notice" role="status">
              Loading map…
            </div>
          }
        >
          <MapView
            cameraRevision={cameraRevision}
            isLoading={recommendations.isFetching}
            results={request ? results : []}
            destinationId={request?.tripworld_region_id ?? null}
            previewDestinationId={destination?.id ?? null}
            onReset={request?.bounds ? startTrip : undefined}
            selectedId={selected?.id ?? null}
            onSelect={setSelectedId}
            onBoundsChange={changeBounds}
            theme={theme}
          />
        </Suspense>
      </section>
      <aside className="glass panel sidebar" aria-label="Trip planner">
        {request && destination ? (
          <TripResults
            destination={destination.name}
            results={results}
            selected={selected}
            onSelect={setSelectedId}
            onEdit={() => {
              setRequest(null);
              setSelectedId(null);
            }}
            resetBounds={request.bounds ? startTrip : undefined}
            loading={recommendations.isFetching}
            failed={recommendations.isError}
            retry={() => recommendations.refetch()}
          />
        ) : !editedTrip && demo.isPending ? (
          <PlannerLoading />
        ) : !editedTrip && demo.isError ? (
          <section>
            <h1>Plan your visit</h1>
            <p role="alert">We couldn’t load the sample trip.</p>
            <Button onClick={() => demo.refetch()}>Try again</Button>
            <Button
              variant="ghost"
              onClick={() => setEditedTrip({ destination: null, visited: [] })}
            >
              Start an empty trip
            </Button>
          </section>
        ) : (
          <TripSetup
            visited={visited}
            destination={destination}
            onInteract={() => setEditedTrip((current) => current ?? trip)}
            setVisited={(next) => setEditedTrip({ destination, visited: next })}
            setDestination={(next) =>
              setEditedTrip({ destination: next, visited })
            }
            submit={startTrip}
          />
        )}
        <footer>Interactive prototype · Sample catalog</footer>
      </aside>
    </main>
  );
}
