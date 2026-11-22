import { Button } from "./ui/Button";
import { Skeleton } from "./ui/Skeleton";
export function PlannerLoading() {
  return (
    <section className="planner-loading">
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
        <div className="visits" aria-hidden="true">
          {[0, 1].map((row) => (
            <div key={row} className="flex h-14 items-center gap-3">
              <Skeleton className="loading-placeholder size-8" />
              <div className="grid flex-1 gap-1.5">
                <Skeleton className="loading-placeholder h-3.5 w-3/5" />
                <Skeleton className="loading-placeholder h-3 w-2/5" />
              </div>
            </div>
          ))}
        </div>
      </section>
      <Button className="primary" disabled>
        Find places
      </Button>
    </section>
  );
}
