const DEFAULT_SERVER_BACKEND_BASE_URL = "http://127.0.0.1:8768";

function normalizeAbsoluteHttpUrl(value: string): string | null {
  try {
    const url = new URL(value);
    if (url.protocol !== "http:" && url.protocol !== "https:") {
      return null;
    }
    return value.replace(/\/+$/, "");
  } catch {
    return null;
  }
}

export function resolveServerBackendBaseUrl(
  env: NodeJS.ProcessEnv = process.env,
): string {
  const explicitServerUrl = env.API_BASE_URL?.trim() || env.BACKEND_API_BASE_URL?.trim();
  if (explicitServerUrl) {
    const normalized = normalizeAbsoluteHttpUrl(explicitServerUrl);
    if (!normalized) {
      throw new Error("API_BASE_URL must be an absolute http(s) URL for server-side fetch.");
    }
    return normalized;
  }

  const publicUrl = env.NEXT_PUBLIC_API_BASE_URL?.trim();
  if (publicUrl) {
    const normalized = normalizeAbsoluteHttpUrl(publicUrl);
    if (normalized) {
      return normalized;
    }
  }

  return DEFAULT_SERVER_BACKEND_BASE_URL;
}
