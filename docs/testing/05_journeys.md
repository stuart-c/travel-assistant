# Test Scenario 05: Multi-Leg Journeys & Trip Windows

## Objective
Validate the creation, modification, tabbed modal dialogue navigation, calculated routes inspection, and persistence of configured journeys between Home Assistant zones, custom locations, and public transit stations.

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

### Scenario 5.2: 2-Tab Modal Dialogue & Calculated Routes Inspection
1. Locate the **Daily Office Commute** journey row.
2. Click the edit button for this row to open the modal dialogue.
3. Verify the modal features 2 distinct navigation tabs:
   * **Journey Details** (active by default)
   * **Calculated Routes**
4. Switch to the **Calculated Routes** tab:
   * Verify that calculated route corridors are rendered with summary (`Walk (8m) → Bus 73 (14m) → Walk (6m)`), total duration (`28m`), and stage legs.
5. Close the modal dialogue.

### Scenario 5.3: Creating a New Multi-Leg Journey
1. Click **+ Add Journey**.
2. In the modal dialogue (**Journey Details** tab), configure:
   * **Journey Name**: `Gym Workout Route`
   * **Origin Type & Location**: Select `Home Assistant Zone` -> `Home` (`ha:home`).
   * **Destination Type & Location**: Select `Home Assistant Zone` -> `City Health Club` (`ha:gym`).
   * **Target Arrival Time**: `07:15`
   * **Buffer Time**: `10` minutes.
3. Switch to the **Calculated Routes** tab and verify the empty placeholder ("No calculated routes found" or notice that routes calculate after save).
4. Click **Add to Table**.
5. Verify the row appears in the Grid.js journeys table.
6. Click **Save Changes** in the bottom action bar.
7. **Expected Result**:
   * Flash message confirms: `Journeys saved successfully.`
   * `Gym Workout Route` is preserved in the database and renders in the table upon reload.

### Scenario 5.4: Editing & Deleting a Journey
1. Locate the **Library Study Session** journey row.
2. Click the edit button for this row.
3. Modify the name to `Central Library Research Session`.
4. Click **Update Row**.
5. Locate the **Weekend Family Visit** row and click the delete button.
6. Click **Save Changes**.
7. **Expected Result**:
   * Updated journey displays the new title and clears stale calculated routes.
   * Deleted journey is permanently removed from the table and database.

---

## Acceptance Criteria
- [ ] Journey origin and destination pickers support HA zones, custom locations, and transit stations.
- [ ] Modal dialogue provides fluid 2-tab navigation (**Journey Details** and **Calculated Routes**).
- [ ] Discovered multi-modal corridors and legs render cleanly in the Calculated Routes tab.
- [ ] Time window settings (target arrival, departure buffer) serialise cleanly.
- [ ] Creation, editing, and deletion reflect accurately across page reloads.
