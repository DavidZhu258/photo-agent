# Photo Agent Web Companion

Next.js companion for the Flutter-first Photo Agent app. It is intentionally
not the core camera/AR product; it supports evidence management and travel
decision review against the same FastAPI backend.

## Run

```powershell
npm install
$env:NEXT_PUBLIC_API_BASE_URL='http://127.0.0.1:8767'
npm run dev -- --hostname 127.0.0.1 --port 3100
```

Use the local `ADMIN_TOKEN` from the backend in the token field. The token is
stored in `sessionStorage` only.

## Test

```powershell
npm test
npm run build
```

Playwright is configured to use the installed Chrome channel on Windows, so it
does not need to download a separate Chromium bundle.
