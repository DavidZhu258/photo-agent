import { readFile, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const shellRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const targetsPath = resolve(shellRoot, "mobile-targets.json");

function mergeObjects(base, override) {
  const result = { ...base };
  for (const [key, value] of Object.entries(override ?? {})) {
    if (
      value &&
      typeof value === "object" &&
      !Array.isArray(value) &&
      base[key] &&
      typeof base[key] === "object" &&
      !Array.isArray(base[key])
    ) {
      result[key] = mergeObjects(base[key], value);
    } else {
      result[key] = value;
    }
  }
  return result;
}

export async function loadTargetRegistry() {
  return JSON.parse(await readFile(targetsPath, "utf8"));
}

export async function buildCapacitorConfig(targetName, env = process.env) {
  const registry = await loadTargetRegistry();
  const target = registry.targets?.[targetName];
  if (!target) {
    const available = Object.keys(registry.targets ?? {}).join(", ");
    throw new Error(`Unknown iOS shell target "${targetName}". Available targets: ${available}`);
  }

  const startUrl =
    env.CAPACITOR_SERVER_URL ||
    env[`CAPACITOR_${targetName.toUpperCase()}_URL`] ||
    target.startUrl;
  const url = new URL(startUrl);
  const isHttp = url.protocol === "http:";

  return mergeObjects(registry.defaults, {
    appId: target.appId,
    appName: target.appName,
    webDir: registry.defaults.webDir,
    server: {
      url: startUrl,
      cleartext: isHttp,
      iosScheme: "capacitor",
      androidScheme: "https"
    },
    ios: {
      scheme: target.displayName,
      contentInset: registry.defaults.ios.contentInset,
      scrollEnabled: registry.defaults.ios.scrollEnabled,
      allowsLinkPreview: registry.defaults.ios.allowsLinkPreview
    },
    plugins: registry.defaults.plugins,
    photoAgent: {
      target: targetName,
      displayName: target.displayName,
      description: target.description,
      cleartextHost: isHttp ? url.hostname : undefined,
      permissions: target.permissions,
      requiredWebCapabilities: target.requiredWebCapabilities,
      nativeLinks: target.nativeLinks
    }
  });
}

async function main() {
  const targetName = process.argv[2];
  const printOnly = process.argv.includes("--print");
  if (!targetName) {
    throw new Error("Usage: node scripts/render-capacitor-config.mjs <unified> [--print]");
  }
  const config = await buildCapacitorConfig(targetName);
  const json = `${JSON.stringify(config, null, 2)}\n`;
  if (printOnly) {
    process.stdout.write(json);
    return;
  }
  await writeFile(resolve(shellRoot, "capacitor.config.json"), json, "utf8");
  process.stdout.write(`Wrote capacitor.config.json for ${targetName}\n`);
}

const invokedPath = process.argv[1] ? resolve(process.argv[1]) : "";

if (fileURLToPath(import.meta.url) === invokedPath) {
  main().catch((error) => {
    console.error(error.message);
    process.exit(1);
  });
}
