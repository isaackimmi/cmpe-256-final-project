import type { StyleSpecification } from "maplibre-gl";
import { atlasCoordinate, type CityAtlas } from "./atlas";

// Keep the world outline visible when the traveler pans beyond the city artwork.
export function previewStyle(
  dark: boolean,
  atlas?: CityAtlas,
): StyleSpecification {
  const style: StyleSpecification = {
    version: 8,
    sources: {
      earth: {
        type: "geojson",
        data: "/map/land.geojson",
        attribution:
          '<a href="https://www.naturalearthdata.com/">Natural Earth</a>',
      },
    },
    layers: [
      {
        id: "water",
        type: "background",
        paint: { "background-color": dark ? "#253e44" : "#c6dde2" },
      },
      {
        id: "land",
        type: "fill",
        source: "earth",
        paint: { "fill-color": dark ? "#3c5047" : "#e8e9d9" },
      },
      {
        id: "coast",
        type: "line",
        source: "earth",
        paint: { "line-color": dark ? "#69816d" : "#9fb3a7", "line-width": 1 },
      },
    ],
  };
  if (atlas) {
    style.sources.city = {
      type: "image",
      url: `/map/atlas/${atlas.slug}-${dark ? "night" : "day"}.webp`,
      coordinates: [
        atlasCoordinate(atlas, 0, 0),
        atlasCoordinate(atlas, 1600, 0),
        atlasCoordinate(atlas, 1600, 1100),
        atlasCoordinate(atlas, 0, 1100),
      ],
    };
    style.layers.push({
      id: "city",
      type: "raster",
      source: "city",
      paint: { "raster-fade-duration": 0 },
    });
  }
  return style;
}
