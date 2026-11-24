"use client";

import { useQuery } from "@tanstack/react-query";
import { fetchJson } from "../lib/api";
import type { Destination, Place, SearchPage } from "../lib/types";

// Resolve the initial sample against the same catalogs used by both pickers.
async function findSample<T extends { id: string }>(
  catalog: "places" | "destinations",
  name: string,
  id: string,
  signal: AbortSignal,
) {
  const query = new URLSearchParams({ q: name });
  const page = await fetchJson<SearchPage<T>>(
    `/api/${catalog}/search?${query}`,
    { signal },
  );
  return page.items.find((item) => item.id === id);
}

export function useDemoTrip() {
  return useQuery({
    queryKey: ["a1-sample-trip", "tripworld-region-ids"],
    staleTime: Infinity,
    queryFn: async ({ signal }) => {
      const [destination, fishHouse, golfCourse] = await Promise.all([
        findSample<Destination>("destinations", "Kyoto", "Q35765", signal),
        findSample<Place>("places", "Fish House", "a1-mamas", signal),
        findSample<Place>("places", "Gold Course", "a1-golf", signal),
      ]);
      if (!destination || !fishHouse || !golfCourse) return null;
      return { destination, visited: [fishHouse, golfCourse] };
    },
  });
}
