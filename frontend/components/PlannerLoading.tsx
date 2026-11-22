import { Button } from "./ui/Button";
import { Skeleton } from "./ui/Skeleton";
export function PlannerLoading() {
  return (
    <section>
      <h1>Plan your visit</h1>
      <span className="section-title">Destination</span>
      <Skeleton
        className="loading-placeholder field-placeholder"
        aria-hidden="true"
      />
      <section className="history-section">
        <h2>Previously visited destinations</h2>
        <p role="status"><span className="sr-only">Loading your trip…</span></p>
        <Skeleton aria-hidden="true" className="loading-placeholder mb-3 h-4 w-3/4" />
        <Skeleton
          className="loading-placeholder field-placeholder"
          aria-hidden="true"
        />
        <div className="visits" aria-hidden="true" />
      </section>
      <Button className="primary" disabled>
        Find places
      </Button>
    </section>
  );
}
