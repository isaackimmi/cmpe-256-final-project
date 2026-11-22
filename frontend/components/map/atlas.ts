type Coordinate = [number, number];
type LabelKind = "district" | "landmark" | "river";
type Label = [name: string, lng: number, lat: number, kind: LabelKind];

export interface CityAtlas {
  name: string;
  slug: string;
  center: Coordinate;
  labels: Label[];
}

export const atlases: Record<string, CityAtlas> = {
  "Q35765": {
    name: "Kyoto",
    slug: "kyoto",
    center: [135.759, 35.008],
    labels: [
      ["KAMIGYŌ", 135.749, 35.025, "district"],
      ["Kyoto Imperial Palace", 135.762, 35.024, "landmark"],
      ["OKAZAKI", 135.783, 35.017, "district"],
      ["Nakagyō", 135.752, 35.011, "district"],
      ["GION", 135.774, 35.005, "district"],
      ["HIGASHIYAMA", 135.784, 34.996, "district"],
      ["Kamo River", 135.769, 35.014, "river"],
      ["Kyoto Station", 135.758, 34.985, "landmark"],
      ["SHIMOGYŌ", 135.751, 34.995, "district"],
    ],
  },
  "Q84": {
    name: "London",
    slug: "london",
    center: [-0.137, 51.509],
    labels: [
      ["MAYFAIR", -0.151, 51.51, "district"],
      ["SOHO", -0.136, 51.515, "district"],
      ["COVENT GARDEN", -0.119, 51.514, "district"],
      ["WESTMINSTER", -0.137, 51.496, "district"],
      ["River Thames", -0.115, 51.506, "river"],
      ["SOUTH BANK", -0.114, 51.502, "district"],
      ["ST JAMES’S", -0.141, 51.507, "district"],
      ["Green Park", -0.145, 51.504, "landmark"],
    ],
  },
};

// The A1 handoff exported 1600 × 1100 Web Mercator images at this world size.
// Invert its pixel projection to anchor each corner and label to the real map.
const worldPixels = 384 * 2 ** 14;
export function atlasCoordinate(
  atlas: CityAtlas,
  x: number,
  y: number,
): Coordinate {
  const [lng, lat] = atlas.center;
  const radians = Math.PI / 180;
  const mercatorY =
    Math.asinh(Math.tan(lat * radians)) -
    ((y - 550) * 2 * Math.PI) / worldPixels;
  return [
    lng + ((x - 800) * 360) / worldPixels,
    Math.atan(Math.sinh(mercatorY)) / radians,
  ];
}

export function atlasZoom(width: number, height: number) {
  return Math.log2((worldPixels / 512) * Math.max(width / 1600, height / 1100));
}
