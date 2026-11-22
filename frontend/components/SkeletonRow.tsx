import { Skeleton } from "./ui/Skeleton";
import { cn } from "../lib/utils";

type Props = {
  className: string;
  iconClassName: string;
};

export function SkeletonRow({ className, iconClassName }: Props) {
  return (
    <div aria-hidden="true" className={cn("flex items-center", className)}>
      <Skeleton className={cn("loading-placeholder shrink-0", iconClassName)} />
      <div className="grid flex-1 gap-1.5">
        <Skeleton className="loading-placeholder h-3.5 w-3/5" />
        <Skeleton className="loading-placeholder h-3 w-2/5" />
      </div>
    </div>
  );
}
