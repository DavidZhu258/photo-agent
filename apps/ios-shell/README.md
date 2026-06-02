# Mira iOS Shell

Windows-first Capacitor shell for one iOS app:

- **Mira 识境** loads the configured travel home and links to the `/visual` discovery feature.

The Web and FastAPI backend remain the source of truth. This shell only adds the
minimum native wrapper needed for TestFlight/self-use: camera/photo access,
share sheet, external browser/maps exits, status bar and keyboard behavior.

## Windows Development

```powershell
cd apps/ios-shell
npm install
npm test
npm run config:print
```

Windows can validate configuration and Web/API behavior. It cannot build or run
iOS apps locally because iOS builds require macOS and Xcode.

## Targets

Target metadata lives in `mobile-targets.json`.

```powershell
npm run config:app
```

That command renders `capacitor.config.json` for the unified Mira app. The rendered
file is ignored because CI/macOS builds should regenerate it.

The default URL is a placeholder for open-source builds:

- Mira: `https://mira-web.example.com/`

Set your deployed Web origin with an environment override:

```powershell
$env:CAPACITOR_UNIFIED_URL='https://your-domain.example/'
```

HTTP is acceptable for local/internal smoke only. A macOS build that keeps HTTP
will need an App Transport Security exception in the generated Xcode project;
`npm run ios:sync` patches the generated `Info.plist` with a WebView-only ATS
exception for the configured HTTP host. Production/TestFlight should use HTTPS.

## macOS / Cloud Build

On a macOS runner or remote Mac:

```bash
cd apps/ios-shell
npm ci
npm run config:app
npx cap add ios
npx cap sync ios
npm run ios:patch-ats
npx cap build ios
```

Recommended cloud options from Windows:

- GitHub Actions macOS runner
- Codemagic
- Ionic Appflow
- Remote Mac mini

## Acceptance Smoke

Mira 识境:

- Launches into the travel chat.
- The mobile header exposes the `Mira` visual entry.
- Camera/photo picker works.
- One image returns one conclusion plus `识别 / 看点 / 线索`.
- Debug/provider details stay inside the folded thinking area.
- Enter/send works with Chinese input.
- Knowledge questions do not force a map.
- Place/itinerary questions show cards and map exits.
- Google Maps, Apple Maps, Mapbox and external source links leave the WebView.
