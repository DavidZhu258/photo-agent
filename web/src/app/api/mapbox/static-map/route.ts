import { NextResponse } from "next/server";

const mapboxToken =
  process.env.MAPBOX_ACCESS_TOKEN ?? process.env.NEXT_PUBLIC_MAPBOX_ACCESS_TOKEN ?? "";

export async function GET(request: Request) {
  if (!mapboxToken) {
    return NextResponse.json({ error: "MAPBOX_ACCESS_TOKEN is not configured" }, { status: 503 });
  }

  const url = new URL(request.url);
  const pins = parsePins(url.searchParams.get("pins") ?? "");
  if (!pins.length) {
    return NextResponse.json({ error: "pins are required" }, { status: 400 });
  }

  const selected = clamp(Number.parseInt(url.searchParams.get("selected") ?? "0", 10), 0, pins.length - 1);
  const width = clamp(Number.parseInt(url.searchParams.get("width") ?? "1200", 10), 320, 1280);
  const height = clamp(Number.parseInt(url.searchParams.get("height") ?? "900", 10), 240, 1280);
  const overlays = pins
    .map((pin, index) => `pin-${index === selected ? "l" : "s"}+${index === selected ? "0369a1" : "111827"}(${pin.lng},${pin.lat})`)
    .join(",");
  const center = pins[selected] ?? pins[0];
  const mapboxUrl = `https://api.mapbox.com/styles/v1/mapbox/streets-v12/static/${overlays}/${center.lng},${center.lat},12.2,0/${width}x${height}@2x?${new URLSearchParams({
    access_token: mapboxToken,
    attribution: "false",
    logo: "false",
  })}`;

  const response = await fetch(mapboxUrl, { cache: "no-store" });
  if (!response.ok || !response.body) {
    return NextResponse.json({ error: `Mapbox static map failed: HTTP ${response.status}` }, { status: 502 });
  }

  return new NextResponse(response.body, {
    status: 200,
    headers: {
      "content-type": response.headers.get("content-type") ?? "image/png",
      "cache-control": "public, max-age=300",
    },
  });
}

function parsePins(value: string): Array<{ lat: number; lng: number }> {
  return value
    .split("|")
    .map((chunk) => {
      const [latText, lngText] = chunk.split(",");
      const lat = Number.parseFloat(latText ?? "");
      const lng = Number.parseFloat(lngText ?? "");
      if (!Number.isFinite(lat) || !Number.isFinite(lng)) {
        return null;
      }
      return { lat, lng };
    })
    .filter((pin): pin is { lat: number; lng: number } => Boolean(pin))
    .slice(0, 12);
}

function clamp(value: number, min: number, max: number): number {
  if (!Number.isFinite(value)) {
    return min;
  }
  return Math.min(max, Math.max(min, value));
}
