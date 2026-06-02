import { NextResponse } from "next/server";

import {
  buildAssistantMessageFromPlan,
  buildMissingDestinationMessage,
  buildTravelPayload,
  mergeContextFromPlan,
  mergeContextFromText,
  textFromMessage,
  type TravelChatMessage,
  type TripContext,
} from "@/lib/travel-chat";
import { resolveServerBackendBaseUrl } from "@/lib/server-backend-url";

type ChatRequest = {
  messages?: TravelChatMessage[];
  context?: TripContext;
};

export async function POST(request: Request) {
  const body = (await request.json()) as ChatRequest;
  const messages = Array.isArray(body.messages) ? body.messages : [];
  const lastUser = [...messages].reverse().find((message) => message.role === "user");
  const query = lastUser ? textFromMessage(lastUser) : "";
  const context = mergeContextFromText(body.context ?? {}, query);

  if (!query.trim()) {
    return NextResponse.json({
      message: buildMissingDestinationMessage(),
      context,
    });
  }

  const backendBaseUrl = resolveServerBackendBaseUrl();
  const backendResponse = await fetch(`${backendBaseUrl}/v1/travel/plan`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(buildTravelPayload(query, context)),
  });

  if (!backendResponse.ok) {
    const detail = await backendResponse.text();
    const warning = travelBackendWarning(detail, backendResponse.status);
    return NextResponse.json(
      {
        message: {
          id: `assistant-${Date.now()}`,
          role: "assistant",
          parts: [
            {
              type: "text",
              text:
                "这次旅行 agent 没有完成必要的模型步骤。我保留了你的问题，可以稍后重试。",
            },
            {
              type: "runtime-warnings",
              warnings: [warning],
            },
          ],
        },
        context,
      },
      { status: 502 },
    );
  }

  const plan = await backendResponse.json();
  const nextContext = mergeContextFromPlan(context, plan, query);
  return NextResponse.json({
    message: buildAssistantMessageFromPlan(plan, nextContext, query),
    context: nextContext,
  });
}

function travelBackendWarning(detail: string, status: number): string {
  try {
    const parsed = JSON.parse(detail) as {
      detail?: {
        error_type?: string;
        failed_stage?: string;
        model?: string;
        message?: string;
      };
    };
    const modelError = parsed.detail;
    if (modelError?.error_type === "travel_model_call_failed") {
      return [
        `Backend HTTP ${status}`,
        modelError.failed_stage ? `stage=${modelError.failed_stage}` : "",
        modelError.model ? `model=${modelError.model}` : "",
        modelError.message ? `message=${modelError.message}` : "",
      ]
        .filter(Boolean)
        .join(" | ");
    }
  } catch {
    // Keep the raw backend text below when it is not JSON.
  }
  return detail || `Backend HTTP ${status}`;
}
