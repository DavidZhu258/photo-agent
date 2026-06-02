import { NextResponse } from "next/server";

const mapboxToken =
  process.env.MAPBOX_ACCESS_TOKEN ?? process.env.NEXT_PUBLIC_MAPBOX_ACCESS_TOKEN ?? "";

type RouteContext = {
  params: Promise<{
    z: string;
    x: string;
    y: string;
  }>;
};

export async function GET(_request: Request, context: RouteContext) {
  if (!mapboxToken) {
    return NextResponse.json({ error: "MAPBOX_ACCESS_TOKEN is not configured" }, { status: 503 });
  }

  const { z, x, y } = await context.params;
  if (!isSafeTileParam(z) || !isSafeTileParam(x) || !isSafeTileParam(y)) {
    return NextResponse.json({ error: "invalid tile coordinates" }, { status: 400 });
  }

  const tileUrl = `https://api.mapbox.com/styles/v1/mapbox/streets-v12/tiles/256/${z}/${x}/${y}@2x?${new URLSearchParams({
    access_token: mapboxToken,
  })}`;
  const response = await fetch(tileUrl, { cache: "force-cache" });
  if (!response.ok || !response.body) {
    return NextResponse.json({ error: `Mapbox tile failed: HTTP ${response.status}` }, { status: 502 });
  }

  return new NextResponse(response.body, {
    status: 200,
    headers: {
      "content-type": response.headers.get("content-type") ?? "image/png",
      "cache-control": "public, max-age=86400",
    },
  });
}

function isSafeTileParam(value: string): boolean {
  return /^\d+$/.test(value);
}
