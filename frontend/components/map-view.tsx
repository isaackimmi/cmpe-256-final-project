"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import * as Mapbox from "react-map-gl/mapbox";
import * as MapLibre from "react-map-gl/maplibre";
import type { Map as MapboxMap } from "mapbox-gl";
import type { Map as MapLibreMap } from "maplibre-gl";
import type { Bounds, Recommendation } from "../lib/types";
import { previewStyle } from "./map/preview-style";
import "mapbox-gl/dist/mapbox-gl.css";
import "maplibre-gl/dist/maplibre-gl.css";
import "./map/map.css";

interface MapViewProps {
  results: Recommendation[];
  destinationId: string | null;
  cameraRevision?: number;
  isLoading?: boolean;
  selectedId: string | null;
  onSelect: (id: string) => void;
  onBoundsChange: (bounds: Bounds) => void;
  theme: "light" | "dark";
}

type Camera = MapboxMap | MapLibreMap;

const token = process.env.NEXT_PUBLIC_MAPBOX_ACCESS_TOKEN;
const Marker = token ? Mapbox.Marker : MapLibre.Marker;
const Navigation = token
  ? Mapbox.NavigationControl
  : MapLibre.NavigationControl;
const initialView = { longitude: 154, latitude: 30, zoom: 1.7 };

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

function viewportBounds(map: Camera): Bounds {
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
        top: padding,
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

export default function MapView({
  results,
  destinationId,
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
  const preview = useMemo(() => previewStyle(theme === "dark"), [theme]);
  const places = useMemo(
    () =>
      results.filter((p) => Number.isFinite(p.lng) && Number.isFinite(p.lat)),
    [results],
  );

  useEffect(() => {
    if (!destinationId) {
      fittedTrip.current = null;
      return;
    }
    const trip = JSON.stringify([destinationId, cameraRevision]);
    if (!camera || isLoading || !places.length || fittedTrip.current === trip)
      return;
    fittedTrip.current = trip;
    fitRecommendations(camera, places);
  }, [camera, cameraRevision, destinationId, isLoading, places]);

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
      <Navigation position="top-right" showCompass={false} />
      {places.map((place) => (
        <Marker
          key={place.id}
          longitude={place.lng}
          latitude={place.lat}
          anchor="bottom"
          style={{ zIndex: selectedId === place.id ? 2 : 1 }}
        >
          <button
            className="map-pin"
            type="button"
            aria-label={`Select ${place.name} on map`}
            aria-pressed={selectedId === place.id}
            onClick={() => onSelect(place.id)}
          >
            {place.rank}
          </button>
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
        <MapLibre.Map {...mapProps} mapStyle={preview}>
          {content}
        </MapLibre.Map>
      )}
      {mapFailed ? (
        <span className="map-status" role="status">
          Map could not load. Places are available in the list.
        </span>
      ) : (
        !token && <span className="map-status">Offline map preview</span>
      )}
    </div>
  );
}
