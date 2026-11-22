export interface Destination {
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

export type Vote = "like" | "dislike";
export interface FeedbackRequest extends RecommendationRequest {
  current_place_ids: string[];
  feedback: { place_id: string; vote: Vote }[];
}
export interface FeedbackResponse extends RecommendationResponse {
  added_place_ids: string[];
  removed_place_ids: string[];
  update_summary: string;
}
