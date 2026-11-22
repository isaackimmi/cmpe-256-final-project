import { plannerStyles } from "./plannerStyles";
import { Skeleton } from "./ui/Skeleton";
import { SkeletonRow } from "./SkeletonRow";

export function PlannerLoading() {
  return (
    <section className="[--skeleton-fill:#d1d5db]">
      <h1>Plan your visit</h1>
      <span className={plannerStyles.label}>Destination</span>
      <Skeleton
        className="h-[43px]"
        aria-hidden="true"
      />
      <section className={plannerStyles.history}>
        <h2>Previously visited destinations</h2>
        <p role="status"><span className="sr-only">Loading your trip…</span></p>
        <Skeleton aria-hidden="true" className="mb-3 h-4 w-3/4" />
        <Skeleton
          className="h-[43px]"
          aria-hidden="true"
        />
        <div className={plannerStyles.visits} aria-hidden="true">
          {[0, 1].map((row) => (
            <SkeletonRow key={row} className="h-14 gap-3" iconClassName="size-8" />
          ))}
        </div>
      </section>
    </section>
  );
}
