"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowLeft, Check, Crosshair, LoaderCircle } from "lucide-react";
import type { Recommendation } from "../lib/types";
import { Button } from "./ui/Button";

type Props = {
  destination: string;
  results: Recommendation[];
  selected?: Recommendation;
  onSelect: (id: string) => void;
  onEdit: () => void;
  resetBounds?: () => void;
  loading: boolean;
  failed: boolean;
  retry: () => void;
};

type Vote = "Like" | "Dislike";
type Votes = Record<string, Vote>;
const voteKey = "tripworld-session-votes";

export function TripResults({
  destination,
  results,
  selected,
  onSelect,
  onEdit,
  resetBounds,
  loading,
  failed,
  retry,
}: Props) {
  const title = useRef<HTMLHeadingElement>(null);
  const [votes, setVotes] = useState<Votes>({});
  useEffect(() => {
    title.current?.focus({ preventScroll: true });
    try {
      const saved: unknown = JSON.parse(
        sessionStorage.getItem(voteKey) ?? "{}",
      );
      if (saved && typeof saved === "object") {
        setVotes(
          Object.fromEntries(
            Object.entries(saved).filter(
              ([, v]) => v === "Like" || v === "Dislike",
            ),
          ),
        );
      }
    } catch {
      /* Session storage may be disabled. */
    }
  }, []);

  function vote(id: string, value: Vote) {
    const next = { ...votes };
    if (next[id] === value) delete next[id];
    else next[id] = value;
    setVotes(next);
    try {
      sessionStorage.setItem(voteKey, JSON.stringify(next));
    } catch {
      /* Keep the vote in memory. */
    }
  }

  return (
    <section className="enter">
      <Button variant="ghost" className="edit" onClick={onEdit}>
        <ArrowLeft size={16} /> Edit trip
      </Button>
      <h1 ref={title} tabIndex={-1}>
        Recommended places
      </h1>
      <p className="subtitle" role="status">
        {loading ? (
          <>
            <LoaderCircle className="spin inline" size={14} />{" "}
            {results.length
              ? "Updating places in this map area…"
              : "Finding places…"}
          </>
        ) : (
          <>For your visit to {destination}</>
        )}
      </p>
      {resetBounds && (
        <Button variant="outline" className="reset" onClick={resetBounds}>
          <Crosshair size={14} /> Search whole destination
        </Button>
      )}
      {failed && (
        <div role="alert" className="notice">
          {results.length
            ? "Couldn’t update this map area. Showing the last available places."
            : "Couldn’t load recommendations."}{" "}
          <Button variant="ghost" onClick={retry}>
            Try again
          </Button>
        </div>
      )}
      {!failed && !loading && !results.length && (
        <div role="status" className="notice">
          No matching places in this area.
        </div>
      )}
      <ol className="rank-list" aria-busy={loading}>
        {loading &&
          !results.length &&
          [0, 1, 2, 3].map((row) => (
            <li
              key={row}
              className="loading-placeholder result-placeholder"
              aria-hidden="true"
            />
          ))}
        {results.map((place) => (
          <li key={place.id}>
            <button
              aria-pressed={selected?.id === place.id}
              onClick={() => onSelect(place.id)}
            >
              <span className="rank">{place.rank}</span>
              <span>
                <strong>{place.name}</strong>
                <small>
                  {[place.category, place.locality].filter(Boolean).join(" · ")}
                </small>
              </span>
            </button>
          </li>
        ))}
      </ol>
      {selected && (
        <div className="detail" aria-live="polite">
          <small>About this match</small>
          <h2>{selected.name}</h2>
          <p>{selected.explanation}</p>
          <div
            className="feedback"
            role="group"
            aria-label="Rate this recommendation for this session"
          >
            {(["Like", "Dislike"] as const).map((value) => (
              <Button
                key={value}
                variant="outline"
                aria-pressed={votes[selected.id] === value}
                onClick={() => vote(selected.id, value)}
              >
                {votes[selected.id] === value && <Check size={14} />} {value}
              </Button>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
