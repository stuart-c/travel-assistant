# Test Scenario 06: Home Assistant Ingress & UI Ergonomics

## Objective
Validate Home Assistant Ingress dynamic subpath routing, static asset URL resolution, responsive layout across mobile and desktop breakpoints, and dark/light theme ergonomics.

## Preconditions
1. Development server running: `bash scripts/run_dev.sh --sample-db`
2. Antigravity `/browser` agent active.

---

## Test Steps

### Scenario 6.1: Home Assistant Ingress Header Simulation
1. Access the application with an `X-Ingress-Path` header simulated:
   * URL: `http://localhost:8099/` with header `X-Ingress-Path: /api/hassio_ingress/token_xyz`
2. Inspect rendered anchor navigation links (e.g., Timetables, Locations, Credentials).
3. Inspect `<link rel="stylesheet">` and `<script src="...">` tags.
4. **Expected Result**:
   * All navigation links resolve with prefix `/api/hassio_ingress/token_xyz/...`.
   * Static assets (`/static/css/tables.css`, `/static/js/*.js`) resolve with the ingress prefix without 404 broken resource errors.
   * Form actions target `/api/hassio_ingress/token_xyz/...`.

### Scenario 6.2: Responsive Mobile & Tablet Viewport
1. Set the browser viewport dimensions to mobile size (`375px` width × `812px` height).
2. Navigate to `http://localhost:8099/config/locations` and `http://localhost:8099/config/timetables`.
3. **Expected Result**:
   * Navigation bar folds or scrolls cleanly without horizontal overflow clipping.
   * Grid.js tables horizontally scroll smoothly with sticky headers/actions where appropriate.
   * Modal dialogs scale fluidly to `w-[90vw]` and maintain accessible close buttons without obscuring input fields.

### Scenario 6.3: Dark & Light Theme Contrast
1. Toggle the operating system / browser preference to `prefers-color-scheme: dark`.
2. Inspect the dashboard, credentials, and table configuration views.
3. **Expected Result**:
   * Background switches to dark slate (`bg-slate-900`/`bg-slate-950`).
   * Text colors maintain high contrast (`text-slate-100`/`text-white`).
   * Input borders, badges, and modal backdrops render with distinct separation without purple-on-dark cliches.

---

## Acceptance Criteria
- [ ] Ingress path prefixing functions flawlessly for assets, links, and forms.
- [ ] UI is fully responsive across mobile (375px), tablet (768px), and desktop (1280px+).
- [ ] Dark and light themes maintain legibility, contrast, and clean visual hierarchy.
