import { useEffect, useRef } from "react";
import { ArrowLeft, Crosshair, LoaderCircle, MapPin } from "lucide-react";
import type { Recommendation } from "../lib/types";
import { Button } from "./ui/Button";

type Props = {
  destination: string;
  results: Recommendation[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  onEdit: () => void;
  resetBounds?: () => void;
  loading: boolean;
  failed: boolean;
  retry: () => void;
  demo: boolean;
};

export function TripResults(props: Props) {
  const { results, selectedId } = props;
  const title = useRef<HTMLHeadingElement>(null);
  useEffect(() => { title.current?.focus({ preventScroll: true }); }, []);
  return (
    <section className="panel-content enter">
      <Button variant="ghost" className="back" onClick={props.onEdit}>
        <ArrowLeft size={15} /> Edit trip
      </Button>
      <div className="heading">
        <h1 ref={title} tabIndex={-1}>{props.destination}</h1>
        <p aria-live="polite">
          {props.failed
            ? "Recommendations unavailable"
            : props.loading
              ? "Finding places…"
              : `${results.length} ${results.length === 1 ? "place" : "places"} ${props.resetBounds ? "in this map area" : "in this destination"}`}
        </p>
      </div>
      {props.resetBounds && (
        <Button variant="outline" className="reset" onClick={props.resetBounds}>
          <Crosshair size={15} /> Search whole destination
        </Button>
      )}
      {props.failed && (
        <div role="alert" className="notice">
          We couldn’t refresh these recommendations.{" "}
          <Button variant="ghost" onClick={props.retry}>
            Try again
          </Button>
        </div>
      )}
      {props.loading && !results.length && (
        <div className="notice" role="status">
          <LoaderCircle className="spin" size={18} /> Loading recommendations…
        </div>
      )}
      {!props.failed && !props.loading && !results.length && (
        <div className="notice">
          <MapPin size={18} /> No matching places in this area.
        </div>
      )}
      <ol className="results">
        {results.map((place) => (
          <li key={place.id}>
            <button
              className="result"
              aria-pressed={selectedId === place.id}
              onClick={() => props.onSelect(place.id)}
            >
              <span className="rank">{place.rank}</span>
              <span>
                <strong>{place.name}</strong>
                <small>{place.explanation}</small>
              </span>
            </button>
          </li>
        ))}
      </ol>
      {props.demo && (
        <p className="demo-note">Showing sample recommendations.</p>
      )}
    </section>
  );
}
