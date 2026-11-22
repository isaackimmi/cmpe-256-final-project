export interface Destination {
  canonical_name?: string | null;
  canonical_metro_label?: string | null;
  matched_alias?: string | null;
  country?: string | null;
  id: string;
  name: string;
}

export interface Place {
  category?: string | null;
  locality?: string | null;
  id: string;
  name: string;
  tripworld_region_id: string;
  lng: number;
  lat: number;
}

export interface Bounds {
  west: number;
  east: number;
  north: number;
  south: number;
}

export interface SearchPage<T> {
  items: T[];
  next_offset: number | null;
}

export interface RecommendationRequest {
  visited_place_ids: string[];
  tripworld_region_id: string;
  bounds?: Bounds;
}

export interface Recommendation extends Place {
  rank: number;
  explanation: string;
}

export interface RecommendationResponse {
  results: Recommendation[];
  model_version: string;
}
