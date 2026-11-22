import { forwardToBackend } from "../../../lib/proxy";

export function POST(request: Request) {
  return forwardToBackend(request, "/recommendations");
}
