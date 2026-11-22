"use client";

import { useState } from "react";
import { TripHeader } from "../components/TripHeader";
import { PlannerLoading } from "../components/PlannerLoading";
import {
  Sidebar,
  SidebarContent,
} from "../components/ui/Sidebar";
import { TripResults } from "../components/TripResults";
import { TripSetup } from "../components/TripSetup";
import { Button } from "../components/ui/Button";
import { useDemoTrip } from "../hooks/useDemoTrip";
import { useRecommendations } from "../hooks/useRecommendations";
import { useTheme } from "../hooks/useTheme";
import type { Destination, Place, RecommendationRequest } from "../lib/types";

type Trip = { destination: Destination | null; visited: Place[] };

export default function Home() {
  const { theme, toggle } = useTheme();
  const demo = useDemoTrip();
  const [editedTrip, setEditedTrip] = useState<Trip | null>(null);
  const trip = editedTrip ?? demo.data ?? { destination: null, visited: [] };
  const { destination, visited } = trip;
  const [restoreSubmitFocus, setRestoreSubmitFocus] = useState(false);
  const [request, setRequest] = useState<RecommendationRequest | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const recommendations = useRecommendations(request);
  const results = recommendations.data?.results ?? [];
  const selected =
    results.find((place) => place.id === selectedId) ?? results[0];

  function startTrip() {
    if (!destination || !visited.length) return;
    setSelectedId(null);
    setRequest({
      tripworld_region_id: destination.id,
      visited_place_ids: visited.map((place) => place.id),
    });
  }

  return (
    <main className="relative isolate h-svh min-h-[420px] overflow-hidden bg-(--maphalo) font-sans text-[15px] leading-[1.4] text-(--ink) max-[700px]:flow-root max-[700px]:h-auto max-[700px]:min-h-svh max-[700px]:overflow-visible max-[700px]:bg-(--glass)">
      <TripHeader theme={theme} toggle={toggle} />
      <Sidebar
        id="trip-planner"
        tabIndex={-1}
        className="glass-surface absolute top-[90px] left-5 z-2 max-h-[calc(100%-112px)] w-[350px] overflow-auto rounded-[22px] p-[25px] max-[700px]:relative max-[700px]:inset-auto max-[700px]:-mt-px max-[700px]:w-full max-[700px]:max-h-none max-[700px]:rounded-[20px_20px_0_0] max-[700px]:px-[21px] max-[700px]:pt-[22px] max-[700px]:pb-5 max-[700px]:[header+&]:mt-[63px]"
        aria-label="Trip planner"
      >
        <SidebarContent className="gap-0 flex-none">
          {request && destination ? (
            <TripResults
              destination={destination.name}
              recommendations={recommendations}
              selected={selected}
              onSelect={setSelectedId}
              onEdit={() => {
                setRestoreSubmitFocus(true);
                setRequest(null);
                setSelectedId(null);
              }}
            />
          ) : !editedTrip && demo.isPending && !demo.isPaused ? (
            <PlannerLoading />
          ) : !editedTrip && (demo.isError || (demo.isPending && demo.isPaused)) ? (
            <section>
              <h1>Plan your visit</h1>
              {demo.isPaused ? (
                <p role="status">The sample trip will load when you’re online.</p>
              ) : (
                <>
                  <p role="alert">We couldn’t load the sample trip.</p>
                  <Button onClick={() => demo.refetch()}>Try again</Button>
                </>
              )}
              <Button
                variant="ghost"
                onClick={() =>
                  setEditedTrip({ destination: null, visited: [] })
                }
              >
                Start an empty trip
              </Button>
            </section>
          ) : (
            <TripSetup
              visited={visited}
              destination={destination}
              onInteract={() => setEditedTrip((current) => current ?? trip)}
              setVisited={(next) =>
                setEditedTrip({ destination, visited: next })
              }
              setDestination={(next) =>
                setEditedTrip({ destination: next, visited })
              }
              submit={startTrip}
              autoFocusSubmit={restoreSubmitFocus}
            />
          )}
        </SidebarContent>
      </Sidebar>
    </main>
  );
}
