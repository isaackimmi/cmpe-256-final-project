import { Skeleton } from "./ui/Skeleton";

export function MapLoading() {
  return (
    <div className="absolute inset-0" role="status">
      <span className="sr-only">Loading map…</span>
      <Skeleton aria-hidden="true" className="size-full bg-(--skeleton-fill)" />
    </div>
  );
}
