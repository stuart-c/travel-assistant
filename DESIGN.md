# Travel Assistant Design System & Architecture Guide

This document establishes the UI/UX design standards, component architecture, and interaction patterns for the **Travel Assistant** web application. Adhering to these guidelines ensures consistent, accessible, and high-performance design across all current and future views.

---

## 1. Language & Copy Standards

- **British English**: All documentation, UI copy, button labels, placeholders, tooltips, and code comments must strictly use British English:
  - `colour` (not *color*, except CSS properties)
  - `-ise` endings: `initialise`, `standardise`, `synchronise`, `optimise`, `categorise`
  - `greyscale` (not *grayscale*)
  - `centre` (not *center*, except CSS properties)
  - `dialogue` (when referring to modal dialogues)
  - `behaviour`, `cancelled`, `programme`, `travelled`

---

## 2. Layout & Container Architecture

- **Wide Layout Hierarchy**: The application layout expands to `max-w-7xl` (`1280px`) on desktop viewports to give ample horizontal width for complex multi-column Grid.js tables, split forms, and interactive widgets.
- **Header Elimination in Config Sub-views**: Within configuration sections (`/config/*`), the global header and redundant breadcrumb bars are omitted. The page begins directly with the configuration layout and sidebar navigation.
- **Responsive Sidebar Navigation**: 
  - Desktop: Left sidebar menu highlighting active page links with smooth hover and focus transitions. Includes a prominent `← Overview` link at the top.
  - Mobile: Slide-out drawer toggleable via top navigation bar.

---

## 3. Collapsible Section Pattern

Pages containing multiple logical sections (e.g. **API Credentials**) organise content into collapsible cards:
- **Structure**: Each section is wrapped in a `.collapsible-section` container styled with rounded corners (`rounded-2xl`), subtle borders, and background shading.
- **Interactive Header**: The header is clickable (`.section-toggle`) and features an animated chevron icon (`.collapsible-chevron`) that smoothly rotates 180° when expanded/collapsed.
- **Header Action Visibility**: Action buttons (`+ Add`, `Check`, status pills) remain pinned and visible in the header even when the section body is collapsed.
- **Default State Rules**:
  - **Multi-entity managers**: Default to **expanded** so users can immediately view tables and interact with content.
  - **API Credentials**: Default to **collapsed** on initial load if the section contains valid, verified credentials. Sections with invalid or missing credentials remain **expanded** for user input.

---

## 4. Action Bar & Dirty State Management

Configuration forms that require persistent saving follow a centralised dirty-tracking and differential persistence architecture:
- **Sticky Action Bar**: Positioned at the top right of configuration pages (`#config-action-bar`), containing **Save Changes** and **Discard** buttons.
- **Visual Icons**: Buttons feature standard Material Symbols icons:
  - Save Changes: `save` icon
  - Discard: `undo` icon
- **State-Driven UX**:
  - **Clean state (Default)**: Both Save Changes and Discard buttons are **disabled** (`opacity-50`, `cursor-not-allowed`) when there are no unsaved changes. There is no redundant "No unsaved changes" badge.
  - **Dirty state**: Both buttons become **active and vibrant** (`bg-sky-600` for Save, `bg-slate-100`/`dark:bg-slate-800` for Discard) as soon as any input or staged table item changes.
  - **Submitting state**: Save Changes displays an animated spinner (`sync`) and disables buttons during network persistence.
- **Client-Side Changeset Payload (`{ added, updated, deleted }`)**:
  - Instead of re-submitting the full dataset on save, client-side scripts track initial states, record deleted record IDs, and compute delta changesets:
    ```json
    {
      "added": [ ...new items... ],
      "updated": [ ...modified items with id... ],
      "deleted": [ id1, id2, ... ]
    }
    ```
  - For simple forms (such as API Credentials), unchanged input fields are disabled immediately before submission so only modified key-value pairs are sent in the HTTP POST request.
- **Differential Server Persistence**:
  - The backend parses the delta changeset and executes targeted database operations within an atomic transaction.
  - Existing records are updated in place with updated `updated_at` timestamps only when values have actually changed.
  - Unchanged records are untouched in the database, preserving original `created_at` and `updated_at` metadata.
  - Scoped filters (such as `ha == False` or `auto_added == False`) ensure protected or external records cannot be deleted or overwritten.
- **Read-Only Exception**: Read-only views (e.g. **Database**, **Background Sync**) omit Save/Discard buttons. The **Database** page repurposes this action bar space to display a compact, styled **Database Size** badge.

---

## 5. Combined Status & Validation Button Pattern

API Credential cards utilise a dual-purpose interactive badge/button (`.check-btn`):
- **Valid State**: Displays a green `Valid` pill with `check_circle` icon.
- **Dirty / Edited State**: Transforms dynamically into an active blue `Check` button with a `refresh` icon the moment any input in that section is modified.
- **Validating State**: Shows a pulsating `Validating...` badge with a rotating spinner.
- **Invalid State**: Displays a red `Invalid` badge with `error` icon, clickable to re-check after correcting values.
- **Empty State**: Disabled grey pill when fields are unconfigured.

---

## 6. Form Controls & Dropdowns

- **AWS Region Select**: Dropdown selector grouped by continent using `<optgroup>` (`Europe`, `North America`, `South America`, `Asia Pacific`, `Middle East & Africa`), with regions ordered alphabetically within each group.
- **Google Maps Region Bias**: Dropdown selector offering a blank default option (`Default (United Kingdom - uk)`) alongside alphabetically sorted two-letter country ccTLD codes (`au`, `ca`, `de`, `es`, `fr`, `ie`, `it`, `nl`, `uk`, `us`, etc.).
- **Time Selectors**: Time fields feature a dropdown datalist (`<datalist id="time-intervals-datalist">`) with 15-minute increments (`00:00` to `23:45`), enabling swift 1-click selection while allowing freeform keyboard input for custom times.
- **Day Selectors & Day Pills**: Consistent day toggle buttons (`M`, `T`, `W`, `T`, `F`, `S`, `S`, `BH`) with quick preset buttons (**Weekdays**, **Weekends**, **All**, **Clear**):
  - **Active**: Blue tint border and background (`border-sky-500 bg-sky-50 dark:bg-sky-950/50 text-sky-700 dark:text-sky-300 font-bold`).
  - **Inactive**: Neutral slate styling (`border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-slate-500 dark:text-slate-400`).

---

## 7. Data Tables (Grid.js) Standards

- **Single-Page Pagination Hiding**: Grid.js tables with 10 or fewer items automatically suppress pagination controls by setting `data-single-page="true"` on `.gridjs-container`.
- **Sorting Exclusions**: Interactive and non-sortable columns explicitly disable sorting (`sort: false`):
  - `Actions` column
  - `Schedule` column
  - `Applicable Days` column
- **Icon-Driven Identity**: Source indicators (e.g. Home Assistant vs Custom) are represented as subtle icons inside the `Name` column rather than occupying a full separate table column.
- **Standard Action Buttons**: Compact 28x28px rounded icon buttons (`w-7 h-7 rounded-lg`) with contextual native tooltips:
  - Edit: `edit` icon (`bg-sky-50 text-sky-600 hover:bg-sky-100`)
  - Delete: `delete` icon (`bg-rose-50 text-rose-600 hover:bg-rose-100`)
  - View (Read-Only): `visibility` icon (`bg-sky-50 text-sky-600`)
  - Refresh: `refresh` icon (`bg-sky-50 text-sky-600`)
- **Empty States**: Tables with 0 items display a centred dashed placeholder card with an icon, descriptive copy, and a primary `+ Add` button.

---

## 8. Modal Dialogues & Read-Only Protection

- **Modal Dimensions**: Modal dialogues use a generous 80% viewport width with bounds: `w-[80vw] max-w-5xl min-w-[320px] mx-auto`, providing ample room for interactive Leaflet maps and multi-column forms.
- **Home Assistant Synchronised Protections**:
  - Synced entities display an informational notice banner explaining their read-only status.
  - Input fields in read-only mode are disabled and styled with greyed-out text and background (`bg-slate-100 dark:bg-slate-800 text-slate-400 dark:text-slate-500 cursor-not-allowed`).
  - Modification and deletion buttons are replaced with a single `Close` button.
