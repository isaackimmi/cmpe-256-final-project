"use client";

import { skipToken, useQuery } from "@tanstack/react-query";
import { fetchJson } from "../lib/api";
import type {
  RecommendationRequest,
  RecommendationResponse,
} from "../lib/types";

export function useRecommendations(request: RecommendationRequest | null) {
  return useQuery({
    queryKey: ["recommendations", request] as const,
    queryFn: request
      ? ({ signal }) =>
          fetchJson<RecommendationResponse>("/api/recommendations", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(request),
            signal,
          })
      : skipToken,
    // Keep pins visible while a pan refreshes the same trip.
    placeholderData: (previous, previousQuery) => {
      const prior = previousQuery?.queryKey[1];
      if (
        request &&
        prior &&
        request.tripworld_region_id === prior.tripworld_region_id &&
        request.visited_place_ids.length === prior.visited_place_ids.length &&
        request.visited_place_ids.every(
          (id, index) => id === prior.visited_place_ids[index],
        )
      ) {
        return previous;
      }
    },
  });
}
