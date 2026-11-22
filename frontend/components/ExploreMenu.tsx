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
        <MenubarTrigger className="bar-context">
          <span className="context-dot" />
          Explore
        </MenubarTrigger>
        <MenubarContent className="explore-links">
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
