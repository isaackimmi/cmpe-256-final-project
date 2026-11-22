"use client";

import { useEffect, useState } from "react";
import { useInfiniteQuery } from "@tanstack/react-query";
import { fetchJson } from "../lib/api";
import type { Destination, Place, SearchPage } from "../lib/types";

function useCatalogSearch<T>(
  catalog: "places" | "destinations",
  text: string,
  active = false,
) {
  const term = text.trim();
  const [settledTerm, setSettledTerm] = useState(term);

  useEffect(() => {
    const timer = setTimeout(() => setSettledTerm(term), 200);
    return () => clearTimeout(timer);
  }, [term]);

  return useInfiniteQuery({
    queryKey: ["search", catalog, term],
    enabled: (active || term.length > 0) && term === settledTerm,
    initialPageParam: 0,
    queryFn: ({ pageParam, signal }) => {
      const params = new URLSearchParams({
        q: term,
        offset: String(pageParam),
        limit: "20",
      });
      return fetchJson<SearchPage<T>>(`/api/${catalog}/search?${params}`, {
        signal,
      });
    },
    getNextPageParam: (page) => page.next_offset ?? undefined,
  });
}

export function usePlaceSearch(text: string, active = false) {
  return useCatalogSearch<Place>("places", text, active);
}

export function useDestinationSearch(text: string, active = false) {
  return useCatalogSearch<Destination>("destinations", text, active);
}
