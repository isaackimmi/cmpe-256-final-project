"use client";

import { useEffect, useState } from "react";
import { skipToken, useQuery } from "@tanstack/react-query";
import { fetchJson } from "../lib/api";
import type {
  RecommendationRequest,
  RecommendationResponse,
} from "../lib/types";

export function useRecommendations(request: RecommendationRequest | null) {
  // A failed viewport request drops TanStack's placeholder. Retain the last
  // successful response for this trip so its pins survive retries as well.
  const tripKey =
    request &&
    JSON.stringify([request.tripworld_region_id, request.visited_place_ids]);
  const [last, setLast] = useState<{
    tripKey: string;
    data: RecommendationResponse;
  } | null>(null);
  const query = useQuery({
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
  });
  useEffect(() => {
    if (tripKey && query.data) setLast({ tripKey, data: query.data });
    if (!tripKey) setLast(null);
  }, [tripKey, query.data]);

  const data =
    query.data ??
    (tripKey && last?.tripKey === tripKey ? last.data : undefined);
  return { ...query, data };
}
