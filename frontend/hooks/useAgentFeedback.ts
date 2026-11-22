"use client";

import { useMutation } from "@tanstack/react-query";
import { fetchJson } from "../lib/api";
import type { FeedbackRequest, FeedbackResponse } from "../lib/types";

export function useAgentFeedback() {
  return useMutation({
    retry: false,
    networkMode: "always",
    mutationFn: (request: FeedbackRequest) =>
      fetchJson<FeedbackResponse>("/api/agent/feedback", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(request),
      }),
  });
}
