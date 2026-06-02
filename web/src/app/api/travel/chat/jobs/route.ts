import { NextResponse } from "next/server";

import {
  buildMissingDestinationMessage,
  buildTravelPayload,
  mergeContextFromText,
  textFromMessage,
  type TravelChatMessage,
  type TripContext,
} from "@/lib/travel-chat";
import { resolveServerBackendBaseUrl } from "@/lib/server-backend-url";

type ChatJobRequest = {
  messages?: TravelChatMessage[];
  context?: TripContext;
};

export async function POST(request: Request) {
  const body = (await request.json()) as ChatJobRequest;
  const messages = Array.isArray(body.messages) ? body.messages : [];
  const lastUser = [...messages].reverse().find((message) => message.role === "user");
  const query = lastUser ? textFromMessage(lastUser) : "";
  const context = mergeContextFromText(body.context ?? {}, query);

  if (!query.trim()) {
    return NextResponse.json({
      status: "completed",
      message: buildMissingDestinationMessage(),
      context,
      query,
    });
  }

  const backendBaseUrl = resolveServerBackendBaseUrl();
  const backendResponse = await fetch(`${backendBaseUrl}/v1/travel/jobs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(buildTravelPayload(query, context)),
  });

  if (!backendResponse.ok) {
    const detail = await backendResponse.text();
    return NextResponse.json(
      {
        status: "failed",
        error: {
          error_type: "travel_job_create_failed",
          message: detail || `Backend HTTP ${backendResponse.status}`,
        },
        context,
        query,
      },
      { status: 502 },
    );
  }

  const job = (await backendResponse.json()) as {
    job_id?: string;
    status?: string;
    poll_url?: string;
  };
  return NextResponse.json(
    {
      ...job,
      context,
      query,
    },
    { status: 202 },
  );
}
