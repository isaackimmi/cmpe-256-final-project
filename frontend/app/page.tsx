"use client";

import { useState } from "react";
import { Compass, Moon, Sun } from "lucide-react";
import { PlannerLoading } from "../components/PlannerLoading";
import {
  Sidebar,
  SidebarContent,
} from "../components/ui/Sidebar";
import { ExploreMenu } from "../components/ExploreMenu";
import { TripSetup } from "../components/TripSetup";
import { Button } from "../components/ui/Button";
import { useDemoTrip } from "../hooks/useDemoTrip";
import { useTheme } from "../hooks/useTheme";
import type { Destination, Place } from "../lib/types";

type Trip = { destination: Destination | null; visited: Place[] };

export default function Home() {
  const { theme, toggle } = useTheme();
  const demo = useDemoTrip();
  const [editedTrip, setEditedTrip] = useState<Trip | null>(null);
  const trip = editedTrip ?? demo.data ?? { destination: null, visited: [] };
  const { destination, visited } = trip;
  return (
    <main className={`trip-design ${theme === "dark" ? "night" : "day"}`}>
      <header className="glass topbar">
        <div className="brand">
          <span className="brand-mark">
            <Compass size={26} />
          </span>
          TripWorld
        </div>
        <ExploreMenu />
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
      <Sidebar
        id="trip-planner"
        tabIndex={-1}
        className="glass panel sidebar"
        aria-label="Trip planner"
      >
        <SidebarContent className="gap-0 flex-none">
          {!editedTrip && demo.isPending && !demo.isPaused ? (
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
            />
          )}
        </SidebarContent>
      </Sidebar>
    </main>
  );
}
