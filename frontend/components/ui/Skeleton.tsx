import { cn } from "../../lib/utils";

function Skeleton({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="skeleton"
      className={cn(
        "rounded-[10px] bg-(--skeleton-fill)",
        className,
      )}
      {...props}
    />
  );
}

export { Skeleton };
