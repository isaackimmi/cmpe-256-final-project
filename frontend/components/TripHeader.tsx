import { Compass, Moon, Sun } from "lucide-react";
import { Button } from "./ui/Button";
import { ExploreMenu } from "./ExploreMenu";

type Props = {
  theme: "light" | "dark";
  toggle: () => void;
  hasMap?: boolean;
};

export function TripHeader({ theme, toggle, hasMap }: Props) {
  return (
    <header className="glass-surface absolute inset-x-5 top-4 z-3 flex h-14 items-center gap-5 rounded-[18px] px-4 max-[700px]:inset-x-2 max-[700px]:top-2 max-[700px]:h-[47px] max-[700px]:gap-2.5 max-[700px]:rounded-[13px] max-[700px]:px-2.5">
      <div className="flex items-center gap-[9px] text-xl font-[740] tracking-[-1px] max-[700px]:text-lg">
        <span className="grid size-[34px] place-items-center rounded-[10px] bg-[#0865db] text-white max-[700px]:size-[30px]">
          <Compass size={26} />
        </span>
        TripWorld
      </div>
      <ExploreMenu hasMap={hasMap} />
      <Button
        variant="ghost"
        className="ml-auto h-auto gap-[7px] rounded-[9px] px-2.5 py-2 text-[13px] font-semibold hover:bg-(--tint) [&_svg]:size-[18px]"
        aria-label={`Switch to ${theme === "light" ? "dark" : "light"} mode`}
        onClick={toggle}
      >
        {theme === "light" ? <Moon size={18} /> : <Sun size={18} />}
        <span className="max-[700px]:hidden">{theme === "light" ? "Dark mode" : "Light mode"}</span>
      </Button>
    </header>
  );
}
