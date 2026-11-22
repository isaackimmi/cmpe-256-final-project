"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import * as Mapbox from "react-map-gl/mapbox";
import * as MapLibre from "react-map-gl/maplibre";
import { Button } from "./ui/Button";
import { Crosshair, Minus, Plus } from "lucide-react";
import { atlasCoordinate, atlases } from "./map/atlas";
import { showTrip, viewportBounds, type Camera } from "./map/camera";
import type { Bounds, Recommendation } from "../lib/types";
import { previewStyle } from "./map/preview-style";
import "mapbox-gl/dist/mapbox-gl.css";
import "maplibre-gl/dist/maplibre-gl.css";
import "./map/map.css";

interface MapViewProps {
  results: Recommendation[];
  destinationId: string | null;
  previewDestinationId?: string | null;
  onReset?: () => void;
  cameraRevision?: number;
  isLoading?: boolean;
  selectedId: string | null;
  onSelect: (id: string) => void;
  onBoundsChange: (bounds: Bounds) => void;
  theme: "light" | "dark";
}

const token = process.env.NEXT_PUBLIC_MAPBOX_ACCESS_TOKEN;
const Marker = token ? Mapbox.Marker : MapLibre.Marker;
const initialView = { longitude: 135.759, latitude: 35.008, zoom: 13.2 };

export default function MapView({
  results,
  destinationId,
  previewDestinationId,
  onReset,
  cameraRevision = 0,
  isLoading,
  selectedId,
  onSelect,
  onBoundsChange,
  theme,
}: MapViewProps) {
  const [camera, setCamera] = useState<Camera | null>(null);
  const [mapFailed, setMapFailed] = useState(false);
  const fittedTrip = useRef<string | null>(null);
  const regionId = destinationId ?? previewDestinationId ?? "demo-kyoto";
  const atlas = atlases[regionId];
  const cityLabel = atlas ? atlasCoordinate(atlas, 690, 510) : null;
  const preview = useMemo(
    () => previewStyle(theme === "dark", atlas),
    [theme, atlas],
  );
  const [labelZoom, setLabelZoom] = useState(initialView.zoom);
  const setupCity = useRef<string | null>(null);
  const places = useMemo(
    () =>
      results.filter((p) => Number.isFinite(p.lng) && Number.isFinite(p.lat)),
    [results],
  );

  useEffect(() => {
    if (!camera) return;
    if (!destinationId) {
      fittedTrip.current = null;
      if (setupCity.current !== regionId) showTrip(camera, regionId, []);
      setupCity.current = regionId;
      return;
    }
    setupCity.current = null;
    const trip = JSON.stringify([destinationId, cameraRevision]);
    if (isLoading || fittedTrip.current === trip) return;
    fittedTrip.current = trip;
    showTrip(camera, regionId, places);
  }, [regionId, camera, cameraRevision, destinationId, isLoading, places]);

  function resetMap() {
    if (!camera) return;
    if (destinationId && onReset) onReset();
    else showTrip(camera, regionId, places);
  }

  const mapProps = {
    initialViewState: initialView,
    dragRotate: false,
    maxPitch: 0,
    touchPitch: false,
    onLoad: (event: { target: Camera }) => {
      event.target.touchZoomRotate.disableRotation();
      setCamera(event.target);
      setMapFailed(false);
    },
    onMoveEnd: (event: { target: Camera; originalEvent?: unknown }) => {
      if (destinationId && event.originalEvent)
        onBoundsChange(viewportBounds(event.target));
    },
    onZoomEnd: (event: { target: Camera }) =>
      setLabelZoom(event.target.getZoom()),
    onIdle: (event: { target: Camera }) => {
      if (event.target.isStyleLoaded()) setMapFailed(false);
    },
    onError: () => {
      // A single missing tile can recover while the rest of the map stays usable.
      if (!camera?.isStyleLoaded()) setMapFailed(true);
    },
  };

  const content = (
    <>
      {!token && atlas && cityLabel && labelZoom >= 11.5 && (
        <>
          <Marker
            longitude={cityLabel[0]}
            latitude={cityLabel[1]}
            style={{ pointerEvents: "none" }}
          >
            <span aria-hidden="true" className="map-label city-label">
              {atlas.name}
            </span>
          </Marker>
          {atlas.labels.map(([name, lng, lat, kind]) => (
            <Marker
              key={name}
              longitude={lng}
              latitude={lat}
              style={{ pointerEvents: "none" }}
            >
              <span aria-hidden="true" className={`map-label ${kind}`}>
                {name}
              </span>
            </Marker>
          ))}
        </>
      )}
      {places.map((place) => (
        <Marker
          key={place.id}
          longitude={place.lng}
          latitude={place.lat}
          anchor="bottom"
          style={{ zIndex: selectedId === place.id ? 2 : 1 }}
        >
          <Button
            variant="ghost"
            size="icon"
            className="map-pin p-0 hover:bg-transparent [&_svg]:size-full"
            type="button"
            aria-label={`Select ${place.name} on map`}
            aria-pressed={selectedId === place.id}
            onClick={() => onSelect(place.id)}
          >
            <svg viewBox="7 0 40 46" aria-hidden="true">
              <circle cx="27" cy="46" r="25" className="pin-halo" />
              <path
                d="M27 43C23 37 10 27 10 16a17 17 0 1 1 34 0c0 11-13 21-17 27Z"
                transform="translate(0 3)"
              />
              <text x="27" y="24" textAnchor="middle">
                {place.rank}
              </text>
            </svg>
          </Button>
        </Marker>
      ))}
    </>
  );

  return (
    <div className="trip-map">
      {token ? (
        <Mapbox.Map
          {...mapProps}
          projection="mercator"
          mapboxAccessToken={token}
          mapStyle={
            theme === "dark"
              ? "mapbox://styles/mapbox/dark-v11"
              : "mapbox://styles/mapbox/streets-v12"
          }
        >
          {content}
        </Mapbox.Map>
      ) : (
        <MapLibre.Map
          {...mapProps}
          mapStyle={preview}
          attributionControl={false}
        >
          {content}
        </MapLibre.Map>
      )}
      <div className="map-tools" role="group" aria-label="Map controls">
        <Button
          variant="ghost"
          size="icon"
          type="button"
          aria-label="Zoom in"
          disabled={!camera}
          onClick={(event) =>
            camera?.zoomIn({}, { originalEvent: event.nativeEvent })
          }
        >
          <Plus size={19} />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          type="button"
          aria-label="Zoom out"
          disabled={!camera}
          onClick={(event) =>
            camera?.zoomOut({}, { originalEvent: event.nativeEvent })
          }
        >
          <Minus size={19} />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          type="button"
          aria-label="Reset map"
          disabled={!camera}
          onClick={resetMap}
        >
          <Crosshair size={17} />
        </Button>
      </div>
      {!token && (
        <div className="map-credits">
          <span>Offline preview</span> ·{" "}
          {atlas && (
            <>
              <a href="https://openfreemap.org/">OpenFreeMap</a> ·{" "}
              <a href="https://openmaptiles.org/">OpenMapTiles</a> ·{" "}
              <a href="https://www.openstreetmap.org/copyright">
                © OpenStreetMap
              </a>{" "}
              ·{" "}
            </>
          )}
          <a href="https://www.naturalearthdata.com/">Natural Earth</a>
        </div>
      )}
      {mapFailed && (
        <span className="map-status" role="status">
          Map could not load. Places are available in the list.
        </span>
      )}
    </div>
  );
}
