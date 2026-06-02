import { expect, test } from "@playwright/test";

import { resolveServerBackendBaseUrl } from "../src/lib/server-backend-url";

test("server backend URL ignores browser-only relative public API base", () => {
  expect(
    resolveServerBackendBaseUrl({
      NEXT_PUBLIC_API_BASE_URL: "/api-backend",
    } as NodeJS.ProcessEnv),
  ).toBe("http://127.0.0.1:8768");
});

test("server backend URL prefers explicit absolute server URL", () => {
  expect(
    resolveServerBackendBaseUrl({
      API_BASE_URL: "http://10.0.0.2:8768/",
      NEXT_PUBLIC_API_BASE_URL: "/api-backend",
    } as NodeJS.ProcessEnv),
  ).toBe("http://10.0.0.2:8768");
});

test("server backend URL accepts absolute public API base for hosted deployments", () => {
  expect(
    resolveServerBackendBaseUrl({
      NEXT_PUBLIC_API_BASE_URL: "https://example.com/api-backend/",
    } as NodeJS.ProcessEnv),
  ).toBe("https://example.com/api-backend");
});

test("server backend URL fails loudly on invalid explicit server URL", () => {
  expect(() =>
    resolveServerBackendBaseUrl({
      API_BASE_URL: "/api-backend",
    } as NodeJS.ProcessEnv),
  ).toThrow(/absolute http\(s\) URL/);
});
