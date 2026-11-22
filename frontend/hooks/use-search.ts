"use client";

import { useEffect, useState } from "react";
import { useInfiniteQuery } from "@tanstack/react-query";
import { fetchJson } from "../lib/api";
import type { Destination, Place, SearchPage } from "../lib/types";

function useCatalogSearch<T>(catalog: "places" | "destinations", text: string) {
  const term = text.trim();
  const [settledTerm, setSettledTerm] = useState(term);

  useEffect(() => {
    const timer = setTimeout(() => setSettledTerm(term), 200);
    return () => clearTimeout(timer);
  }, [term]);

  return useInfiniteQuery({
    queryKey: ["search", catalog, term],
    enabled: term.length > 0 && term === settledTerm,
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

export function usePlaceSearch(text: string) {
  return useCatalogSearch<Place>("places", text);
}

export function useDestinationSearch(text: string) {
  return useCatalogSearch<Destination>("destinations", text);
}
