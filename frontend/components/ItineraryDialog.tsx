"use client";

import { Sparkles } from "lucide-react";
import { useState } from "react";
import { useAgentFeedback } from "../hooks/useAgentFeedback";
import type {
  FeedbackRequest,
  FeedbackResponse,
  Recommendation,
  RecommendationRequest,
  Vote,
} from "../lib/types";
import { plannerStyles } from "./plannerStyles";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogTitle,
  DialogTrigger,
} from "./ui/Dialog";
import { Button } from "./ui/Button";
import { Alert } from "./ui/Alert";
import { Badge } from "./ui/Badge";
import { ScrollArea } from "./ui/ScrollArea";
import { ToggleGroup, ToggleGroupItem } from "./ui/ToggleGroup";

type Votes = Record<string, Vote>;

function PlaceFeedback({
  place,
  vote,
  busy,
  change,
}: {
  place: Recommendation;
  vote?: Vote;
  busy: boolean;
  change: (value: Vote | "") => void;
}) {
  return (
    <ToggleGroup
      type="single"
      aria-label={`Rate ${place.name}`}
      value={vote ?? ""}
      disabled={busy}
      onValueChange={change}
      className="flex gap-2"
    >
      <ToggleGroupItem value="like">Like</ToggleGroupItem>
      <ToggleGroupItem value="dislike">Dislike</ToggleGroupItem>
    </ToggleGroup>
  );
}

function ItineraryPlaceCard({
  place,
  vote,
  added,
  busy,
  change,
}: {
  place: Recommendation;
  vote?: Vote;
  added: boolean;
  busy: boolean;
  change: (value: Vote | "") => void;
}) {
  return (
    <li className="grid gap-2 border-b border-(--edge) py-3">
      <div className="flex items-center gap-2">
        <strong>
          {place.rank}. {place.name}
        </strong>
        {vote === "like" ? <Badge>Kept</Badge> : added && <Badge>New</Badge>}
      </div>
      <p className="text-sm text-(--muted)">{place.explanation}</p>
      <PlaceFeedback place={place} vote={vote} busy={busy} change={change} />
    </li>
  );
}

interface Props {
  request: RecommendationRequest;
  destination: string;
  results: Recommendation[];
  refined: FeedbackResponse | null;
  open: boolean;
  setOpen: (open: boolean) => void;
  enabled: boolean;
  accept: (result: FeedbackResponse) => void;
}

export function ItineraryDialog({
  request,
  destination,
  results,
  refined,
  open,
  setOpen,
  enabled,
  accept,
}: Props) {
  const mutation = useAgentFeedback();
  const [votes, setVotes] = useState<Votes>({});
  const [names, setNames] = useState<Record<string, string>>({});
  function submit(payload: FeedbackRequest) {
    mutation.mutate(payload, {
      onSuccess: (data) => {
        setVotes(
          Object.fromEntries(payload.feedback.map((v) => [v.place_id, v.vote])),
        );
        accept(data);
      },
    });
  }
  function change(id: string, value: Vote | "") {
    const next = { ...votes };
    if (value) next[id] = value;
    else delete next[id];
    setNames((previous) => ({
      ...previous,
      ...Object.fromEntries(results.map((p) => [p.id, p.name])),
    }));
    submit({
      ...request,
      current_place_ids: results.map((p) => p.id),
      feedback: Object.entries(next).map(([place_id, vote]) => ({
        place_id,
        vote,
      })),
    });
  }
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button
          size="sm"
          disabled={!enabled}
          className="rounded-lg bg-[#0865db] text-white hover:bg-[#075cc5]"
        >
          <Sparkles aria-hidden="true" className="size-4" />
          Build itinerary
        </Button>
      </DialogTrigger>
      <DialogContent>
        <header className="pb-3">
          <DialogTitle className="text-xl font-semibold">
            Your {destination} itinerary
          </DialogTitle>
          <DialogDescription className="text-sm text-(--muted)">
            Like places to keep them or dislike them to update your
            recommendations.
          </DialogDescription>
        </header>
        <ScrollArea viewportClassName="max-h-[55dvh]">
          <ol>
            {results.map((place) => (
              <ItineraryPlaceCard
                key={place.id}
                place={place}
                vote={votes[place.id]}
                added={refined?.added_place_ids.includes(place.id) ?? false}
                busy={mutation.isPending}
                change={(value) => change(place.id, value)}
              />
            ))}
          </ol>
          {Object.entries(votes)
            .filter(([, v]) => v === "dislike")
            .map(([id]) => (
              <Button
                key={id}
                variant="ghost"
                disabled={mutation.isPending}
                onClick={() => change(id, "")}
              >
                Undo dislike for {names[id] ?? id}
              </Button>
            ))}
        </ScrollArea>
        <footer className="grid gap-2 pt-3">
          <span role="status" className="text-sm text-(--muted)">
            {mutation.isPending ? "Updating places…" : refined?.update_summary}
          </span>
          {mutation.isError && (
            <Alert>
              {mutation.error.message}{" "}
              <Button
                variant="outline"
                onClick={() => submit(mutation.variables)}
              >
                Retry
              </Button>
            </Alert>
          )}
          <DialogClose asChild>
            <Button className={plannerStyles.primaryButton}>Done</Button>
          </DialogClose>
        </footer>
      </DialogContent>
    </Dialog>
  );
}
