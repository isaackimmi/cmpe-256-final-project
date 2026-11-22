import { Skeleton } from "./ui/Skeleton";
import { SkeletonRow } from "./SkeletonRow";

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
            <SkeletonRow key={row} className="h-14 gap-3" iconClassName="size-8" />
          ))}
        </div>
      </section>
    </section>
  );
}
