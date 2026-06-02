import assert from "node:assert/strict";
import { test } from "node:test";

import { buildCapacitorConfig, loadTargetRegistry } from "../scripts/render-capacitor-config.mjs";
import { cleartextHostFromConfig } from "../scripts/patch-ios-info-plist.mjs";

test("target registry defines one unified Mira product shell", async () => {
  const registry = await loadTargetRegistry();
  assert.deepEqual(Object.keys(registry.targets).sort(), ["unified"]);
  assert.equal(registry.targets.unified.appName, "Mira 识境");
  assert.equal(registry.targets.unified.displayName, "Mira 识境");
});

test("unified shell config opens the deployed Mira home and exposes both core capabilities", async () => {
  const config = await buildCapacitorConfig("unified");
  assert.equal(config.appId, "com.photoagent.mira");
  assert.equal(config.appName, "Mira 识境");
  assert.equal(config.server.url, "http://87.99.146.185:3101/");
  assert.equal(config.server.cleartext, true);
  assert.equal(config.photoAgent.cleartextHost, "87.99.146.185");
  assert.equal(cleartextHostFromConfig(config), "87.99.146.185");
  assert.equal(config.photoAgent.target, "unified");
  assert.deepEqual(config.photoAgent.permissions, [
    "Camera",
    "PhotoLibrary",
    "MicrophoneForSpeechPlayback",
    "LocationWhenInUseOptional",
  ]);
  assert.ok(config.photoAgent.requiredWebCapabilities.includes("travelChat"));
  assert.ok(config.photoAgent.requiredWebCapabilities.includes("recommendationCards"));
  assert.ok(config.photoAgent.requiredWebCapabilities.includes("conditionalMapPanel"));
  assert.ok(config.photoAgent.requiredWebCapabilities.includes("visualDeepCards"));
  assert.ok(config.photoAgent.requiredWebCapabilities.includes("singleImageUpload"));
  assert.ok(config.photoAgent.nativeLinks.includes("appleMaps"));
  assert.ok(config.photoAgent.nativeLinks.includes("googleMaps"));
  assert.ok(config.photoAgent.nativeLinks.includes("shareSheet"));
});

test("environment URL override supports staging and future HTTPS deployment", async () => {
  const config = await buildCapacitorConfig("unified", {
    CAPACITOR_UNIFIED_URL: "https://mira.example.com/",
  });
  assert.equal(config.server.url, "https://mira.example.com/");
  assert.equal(config.server.cleartext, false);
  assert.equal(config.photoAgent.cleartextHost, undefined);
  assert.equal(cleartextHostFromConfig(config), null);
});

test("unknown target fails loudly instead of producing a wrong shell", async () => {
  await assert.rejects(
    () => buildCapacitorConfig("unknown"),
    /Unknown iOS shell target/,
  );
});
