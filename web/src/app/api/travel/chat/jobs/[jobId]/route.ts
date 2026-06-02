import { NextResponse } from "next/server";

import { resolveServerBackendBaseUrl } from "@/lib/server-backend-url";

type RouteContext = {
  params: Promise<{
    jobId: string;
  }>;
};

export async function GET(_request: Request, context: RouteContext) {
  const { jobId } = await context.params;
  if (!/^[a-zA-Z0-9_-]+$/.test(jobId)) {
    return NextResponse.json({ error: "invalid travel job id" }, { status: 400 });
  }

  const backendBaseUrl = resolveServerBackendBaseUrl();
  const backendResponse = await fetch(`${backendBaseUrl}/v1/travel/jobs/${jobId}`, {
    cache: "no-store",
  });
  const text = await backendResponse.text();
  const contentType = backendResponse.headers.get("content-type") ?? "application/json";
  if (!backendResponse.ok) {
    return new NextResponse(text || `Backend HTTP ${backendResponse.status}`, {
      status: backendResponse.status === 404 ? 404 : 502,
      headers: { "content-type": contentType },
    });
  }
  return new NextResponse(text, {
    status: 200,
    headers: {
      "content-type": contentType,
      "cache-control": "no-store",
    },
  });
}
