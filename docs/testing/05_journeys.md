# Test Scenario 05: Multi-Leg Journeys & Trip Windows

## Objective
Validate the creation, modification, and persistence of configured journeys between Home Assistant zones, custom locations, and public transit stations.

## Preconditions
1. Development server running: `bash scripts/run_dev.sh --sample-db`
2. Target URL: `http://localhost:8099/config/journeys`
3. Antigravity `/browser` agent active.

---

## Test Steps

### Scenario 5.1: Journeys Table & Pre-Seeded Routes
1. Navigate to `http://localhost:8099/config/journeys`.
2. Verify page title is `Journeys - Travel Assistant`.
3. Check that pre-seeded journeys render in the Grid.js table:
   * **Daily Office Commute** (Origin: `Home`, Destination: `Tech Campus`).
   * **Library Study Session** (Origin: `Home`, Destination: `Central Public Library`).
   * **Intercity Journey: London to Manchester** (Origin: `London Euston`, Destination: `Manchester Piccadilly`).

### Scenario 5.2: Creating a New Multi-Leg Journey
1. Click **+ Add Journey**.
2. In the modal dialog, configure:
   * **Journey Name**: `Gym Workout Route`
   * **Origin Type & Location**: Select `Home Assistant Zone` -> `Home` (`zone.home`).
   * **Destination Type & Location**: Select `Home Assistant Zone` -> `City Health Club` (`zone.gym`).
   * **Target Arrival Time**: `07:15`
   * **Buffer Time**: `10` minutes.
3. Click **Add to Table**.
4. Verify the row appears in the Grid.js journeys table.
5. Click **Save Changes** in the bottom action bar.
6. **Expected Result**:
   * Flash message confirms: `Journeys saved successfully.`
   * `Gym Workout Route` is preserved in the database and renders in the table upon reload.

### Scenario 5.3: Editing & Deleting a Journey
1. Locate the **Library Study Session** journey row.
2. Click the edit button for this row.
3. Modify the name to `Central Library Research Session`.
4. Click **Update Row**.
5. Locate the **Weekend Family Visit** row and click the delete button.
6. Click **Save Changes**.
7. **Expected Result**:
   * Updated journey displays the new title.
   * Deleted journey is permanently removed from the table and database.

---

## Acceptance Criteria
- [ ] Journey origin and destination pickers support HA zones, custom locations, and transit stations.
- [ ] Time window settings (target arrival, departure buffer) serialise cleanly.
- [ ] Creation, editing, and deletion reflect accurately across page reloads.
