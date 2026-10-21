# Sentinel Console — vendored UI

Vendored copy of the "Sentinel v2" analyst console (Team CollabUp, Hacker House Goa),
branch `sentinel-v2` of https://github.com/r-rishit27/hacker_house,
commit `7bcea03` (shallow clone, 2026-09-24 push).

Source: https://github.com/r-rishit27/hacker_house/tree/sentinel-v2

**No LICENSE file exists in the upstream repository.** The upstream authors retain
all rights by default; this vendored copy is not redistribution-licensed. Attribution
to Team CollabUp is provided here in good faith.

Contains changes from upstream: this NOTICE file, plus the deployment-surface
changes below (component/state logic is untouched).

## Deployment deviations from upstream `7bcea03`

The upstream API CORS-allowlists `localhost` origins only, so a hosted console
cannot call it from the browser. Two file-level additions make the hosted build
reach the same upstream contract server-to-server:

- `next.config.ts` — added a same-origin rewrite: `/api/:path*` →
  `${API_PROXY_ORIGIN}/api/:path*` (default `https://apihacker.collabup.co.in`,
  overridable via `API_PROXY_ORIGIN`). Engages only when the UI talks to its own
  origin; local `npm run dev` still calls `127.0.0.1:8000` directly.
- `src/lib/api.ts` — `API_BASE` now supports an empty value (same-origin mode:
  relative `/api/...` resolved against `window.location.origin` in `url()`);
  unset env still defaults to `http://127.0.0.1:8000` as upstream.
- `.env.production` — sets `NEXT_PUBLIC_API_BASE=` (empty) so hosted builds use
  the same-origin proxy encoded above.

## Known upstream issues (code review of the vendored copy)

- `src/lib/hooks.ts` SSE listener: `JSON.parse(raw.data)` has no try/catch; a malformed event silently kills stream updates.
- `src/lib/api.ts`: case ids interpolated into URL paths without `encodeURIComponent`.
- `src/lib/hooks.ts` `useCopy`: un-cleared `setTimeout` after unmount.
- Authorization is a client-supplied `X-Sentinel-Role` header; trust lives server-side **in the upstream backend**, which is not part of this repo.

Left unmodified on purpose — this is an exact vendored copy of upstream `7bcea03`.

## Run

```bash
cd sentinel-ui
npm install
npm run dev          # http://localhost:3000
```

By default the console calls its own backend contract at `http://127.0.0.1:8000`.
To run it against the upstream team's deployed API (verified working, CORS-allowed
for localhost:3000):

```bash
# PowerShell
$env:NEXT_PUBLIC_API_BASE = "https://apihacker.collabup.co.in"
npm run dev
```

This app is vendored alongside (not merged into) HHGOA's own frontend and does not
talk to the HHGOA backend; the HHGOA API contract is unchanged by its presence.
