import { forwardToBackend } from "../../../../lib/proxy";

export function GET(request: Request) {
  return forwardToBackend(request, "/destinations/search");
}
