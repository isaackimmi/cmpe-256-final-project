"use client";

import {
  Menubar,
  MenubarMenu,
  MenubarTrigger,
  MenubarContent,
  MenubarItem,
} from "./ui/Menubar";

export function ExploreMenu({ hasMap = false }: { hasMap?: boolean }) {
  return (
    <Menubar
      aria-label="Explore navigation"
      className="h-auto border-0 bg-transparent p-0 shadow-none"
    >
      <MenubarMenu>
        <MenubarTrigger className="gap-[7px] rounded-full bg-(--tint) px-3 py-[5px] text-[13px] font-[650] text-(--blue)">
          <span className="size-1.5 rounded-full bg-current" />
          Explore
        </MenubarTrigger>
        <MenubarContent className="bg-(--surface) text-(--ink) [&_[data-highlighted]]:bg-[#0865db] [&_[data-highlighted]]:text-white">
          <MenubarItem asChild>
            <a href="#trip-planner">Trip planner</a>
          </MenubarItem>
          {hasMap && (
            <MenubarItem asChild>
              <a href="#trip-map">Recommendation map</a>
            </MenubarItem>
          )}
        </MenubarContent>
      </MenubarMenu>
    </Menubar>
  );
}
