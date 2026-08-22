# Test Scenario 02: Locations & Geographic Waypoints

## Objective
Validate custom location creation, geographic coordinate validation, Home Assistant zone syncing (read-only protections), transit place search autocomplete, and Grid.js interactive table bindings.

## Preconditions
1. Development server running: `bash scripts/run_dev.sh --sample-db`
2. Target URL: `http://localhost:8099/config/locations`
3. Antigravity `/browser` agent active.

---

## Test Steps

### Scenario 2.1: Grid.js Table Initial Load & Seeded Places
1. Navigate to `http://localhost:8099/config/locations`.
2. Verify the page title is `Locations - Travel Assistant`.
3. Verify that the Grid.js table mounts properly in `#locations-grid-wrapper`.
4. Check that pre-seeded sample locations appear in the table:
   * **Home** (`ha:home`) with HA badge indicating synchronised status.
   * **Tech Campus** (`ha:work`) with HA badge.
   * **Central Public Library** (`custom:...`) as a custom location.

### Scenario 2.2: Home Assistant Read-Only Protection
1. Locate the **Home** (`ha:home`) row in the table.
2. Click the edit button for this row.
3. **Expected Result**:
   * The location modal opens with an informative banner: `This location is synchronised from Home Assistant and is read-only. Coordinates and names cannot be edited or deleted here.`
   * Name, Latitude, and Longitude inputs are disabled.
   * The Delete button is disabled or hidden.
4. Close the modal by clicking the close button (`✕`) or pressing `Escape`.

### Scenario 2.3: Adding a Custom Location via Modal
1. Click the **+ Add Location** button (top right header).
2. Verify the modal dialogue opens titled `Add New Location`.
3. Enter the following details:
   * **Location Name**: `St Pancras International Library`
   * **Latitude**: `51.5310`
   * **Longitude**: `-0.1260`
4. Click **Add to Table**.
5. Verify that the new location row appears in the Grid.js table.
6. Verify the **Save Changes** banner/bar activates (indicating dirty state).
7. Click **Save Changes**.
8. **Expected Result**:
   * The page saves and reloads.
   * `St Pancras International Library` persists in the Grid.js table upon reload.

### Scenario 2.4: Geographic Coordinate Validation
1. Click **+ Add Location**.
2. Enter Name: `Invalid Coord Test`, Latitude: `95.00` (exceeds 90.0 maximum), Longitude: `0.0`.
3. Click **Add to Table** or attempt to save.
4. **Expected Result**:
   * Client-side HTML5 input validation triggers (latitude must be between -90 and 90).
   * Form cannot be submitted with out-of-range coordinates.

---

## Acceptance Criteria
- [ ] Grid.js renders all custom and HA locations with sorting and search.
- [ ] Home Assistant zones are properly guarded as read-only.
- [ ] Custom locations can be added, edited, and deleted.
- [ ] Dirty state banner correctly prompts the user to save table modifications.
