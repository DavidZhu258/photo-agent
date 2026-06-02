import { access, readFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const shellRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const plistPath = resolve(shellRoot, "ios/App/App/Info.plist");
const configPath = resolve(shellRoot, "capacitor.config.json");

function runPlistBuddy(args) {
  execFileSync("/usr/libexec/PlistBuddy", args, { stdio: "ignore" });
}

function tryPlistBuddy(args) {
  try {
    runPlistBuddy(args);
    return true;
  } catch {
    return false;
  }
}

function ensureBool(path, value) {
  if (!tryPlistBuddy(["-c", `Set ${path} ${value ? "true" : "false"}`, plistPath])) {
    runPlistBuddy(["-c", `Add ${path} bool ${value ? "true" : "false"}`, plistPath]);
  }
}

function ensureString(path, value) {
  const safeValue = String(value ?? "").trim();
  if (!safeValue) {
    return;
  }
  if (!tryPlistBuddy(["-c", `Set ${path} ${safeValue}`, plistPath])) {
    runPlistBuddy(["-c", `Add ${path} string ${safeValue}`, plistPath]);
  }
}

function ensureDict(path) {
  tryPlistBuddy(["-c", `Add ${path} dict`, plistPath]);
}

export function cleartextHostFromConfig(config) {
  const url = config.server?.url ? new URL(config.server.url) : null;
  return url?.protocol === "http:" ? url.hostname : null;
}

export async function patchIosInfoPlist() {
  await access(plistPath);
  const config = JSON.parse(await readFile(configPath, "utf8"));
  const host = cleartextHostFromConfig(config);
  ensureString(":CFBundleDisplayName", config.photoAgent?.displayName || config.appName);

  if (!host) {
    process.stdout.write("Patched iOS display name; no HTTP server URL detected, ATS patch skipped.\n");
    return;
  }

  ensureDict(":NSAppTransportSecurity");
  ensureBool(":NSAppTransportSecurity:NSAllowsArbitraryLoadsInWebContent", true);
  ensureDict(":NSAppTransportSecurity:NSExceptionDomains");
  ensureDict(`:NSAppTransportSecurity:NSExceptionDomains:${host}`);
  ensureBool(`:NSAppTransportSecurity:NSExceptionDomains:${host}:NSExceptionAllowsInsecureHTTPLoads`, true);
  ensureBool(`:NSAppTransportSecurity:NSExceptionDomains:${host}:NSIncludesSubdomains`, true);

  process.stdout.write(`Patched iOS display name and ATS WebView exception for ${host}\n`);
}

const invokedPath = process.argv[1] ? resolve(process.argv[1]) : "";

if (fileURLToPath(import.meta.url) === invokedPath) {
  patchIosInfoPlist().catch((error) => {
    console.error(error.message);
    process.exit(1);
  });
}
