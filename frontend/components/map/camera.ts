import type { Map as MapboxMap } from "mapbox-gl";
import type { Map as MapLibreMap } from "maplibre-gl";
import type { Bounds, Recommendation } from "../../lib/types";
import { atlasZoom, atlases } from "./atlas";

export type Camera = MapboxMap | MapLibreMap;

function wrapLongitude(lng: number) {
  return ((((lng + 180) % 360) + 360) % 360) - 180;
}

// Fit pins into the visible area beside the floating desktop panel.
function sidebarInset(map: Camera) {
  const mapBox = map.getContainer().getBoundingClientRect();
  const panel = document
    .querySelector("aside[aria-label='Trip planner']")
    ?.getBoundingClientRect();
  if (!panel || panel.top >= mapBox.bottom || panel.bottom <= mapBox.top)
    return 0;
  return Math.max(0, Math.min(panel.right - mapBox.left, mapBox.width / 2));
}

export function viewportBounds(map: Camera): Bounds {
  const bounds = map.getBounds();
  const west = bounds.getWest();
  const east = bounds.getEast();
  const wholeWorld = east - west >= 360;
  return {
    west: wholeWorld ? -180 : wrapLongitude(west),
    east: wholeWorld ? 180 : wrapLongitude(east),
    north: Math.min(90, bounds.getNorth()),
    south: Math.max(-90, bounds.getSouth()),
  };
}

function fitRecommendations(map: Camera, places: Recommendation[]) {
  const first = places[0];
  const lngs = places.map((p) => first.lng + wrapLongitude(p.lng - first.lng));
  const lats = places.map((p) => p.lat);
  const padding = Math.min(
    40,
    map.getContainer().clientHeight / 6,
    map.getContainer().clientWidth / 8,
  );
  map.fitBounds(
    [
      [Math.min(...lngs), Math.min(...lats)],
      [Math.max(...lngs), Math.max(...lats)],
    ],
    {
      padding: {
        top: Math.max(
          padding,
          Math.min(map.getContainer().clientHeight / 3, 112),
        ),
        bottom: padding,
        left: sidebarInset(map) + padding,
        right: padding,
      },
      maxZoom: 14,
      duration: matchMedia("(prefers-reduced-motion: reduce)").matches
        ? 0
        : 400,
    },
  );
}

export function showTrip(
  map: Camera,
  regionId: string,
  places: Recommendation[],
) {
  const container = map.getContainer();
  const atlas = atlases[regionId];
  if (atlas) {
    map.jumpTo({
      center: atlas.center,
      zoom: atlasZoom(container.clientWidth, container.clientHeight),
      padding: { left: 0, right: 0, top: 0, bottom: 0 },
    });
    const inset = sidebarInset(map);
    const header = document.querySelector("header")?.getBoundingClientRect();
    const top = Math.max(
      0,
      (header?.bottom ?? 0) - container.getBoundingClientRect().top,
    );
    // Keep the approved city framing whenever all result markers remain usable.
    const visible = places.every((place) => {
      const { x, y } = map.project([place.lng, place.lat]);
      return (
        x > inset + 20 &&
        x < container.clientWidth - 20 &&
        y > top + 44 &&
        y < container.clientHeight - 16
      );
    });
    if (visible) return;
  }
  if (places.length) {
    fitRecommendations(map, places);
  } else if (!atlas) {
    const maui = regionId === "demo-maui";
    map.jumpTo({
      center: maui ? [-156.33, 20.8] : [0, 20],
      zoom: maui ? 8.4 : 1.5,
      padding: { top: 0, bottom: 0, left: 0, right: 0 },
    });
  }
}
