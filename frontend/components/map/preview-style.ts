import type { StyleSpecification } from "maplibre-gl";

// The local preview uses Natural Earth land outlines distributed by world-atlas.
// It requires neither an access token nor external tile requests.
export function previewStyle(dark: boolean): StyleSpecification {
  return {
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
}
