# Test Scenario 04: Interchange Transfers & Platform Transitions

## Objective
Validate the configuration of inter-location walking links (between stations/bus stops) and within-station platform transfer durations with step-free accessibility flags.

## Preconditions
1. Development server running: `bash scripts/run_dev.sh --sample-db`
2. Target URL: `http://localhost:8099/config/transfers`
3. Antigravity `/browser` agent active.

---

## Test Steps

### Scenario 4.1: Inter-Location & Platform Transfer Tables
1. Navigate to `http://localhost:8099/config/transfers`.
2. Verify page title is `Transfers - Travel Assistant`.
3. Verify that two distinct tables are presented:
   * **Location Transfers (Inter-modal / Station walking links)**.
   * **Platform Transfers (Station interchange durations)**.
4. Verify seeded transfers render in the respective tables:
   * **London King's Cross to London St Pancras International** (4 minutes, Step-Free badge `✓`, Bidirectional badge `⇄`).
   * **London King's Cross Platform 1 to Platform 8** (4 minutes, Step-Free badge `✓`).

### Scenario 4.2: Adding a Walking Connection between Stations
1. Click **+ Add Location Transfer**.
2. In the modal dialog, configure:
   * **From Place**: Search or select `London Euston` (Rail).
   * **To Place**: Search or select `London King's Cross` (Rail).
   * **Transfer Duration**: `10` minutes.
   * **Bidirectional**: Checked (`Yes`).
   * **Step-Free Access**: Checked (`Yes`).
   * **Notes**: `Pedestrian walk via Euston Road.`
3. Click **Add to Table**.
4. Verify the row appears in the Location Transfers table.
5. Click **Save Changes** in the bottom action bar.
6. **Expected Result**:
   * Flash confirmation: `Transfers saved successfully.`
   * New transfer persists upon page reload.

### Scenario 4.3: Adding a Platform Interchange Transfer
1. In the Platform Transfers section, click **+ Add Platform Transfer**.
2. In the modal dialog, configure:
   * **Station**: Select `London Euston`.
   * **From Platform**: `1`
   * **To Platform**: `8`
   * **Transfer Duration**: `3` minutes.
   * **Step-Free**: Checked.
3. Click **Add to Table** and save changes.
4. **Expected Result**:
   * Platform transfer persists with 3 minutes duration and step-free indicator.

---

## Acceptance Criteria
- [ ] Both Location and Platform transfer tables mount and render data cleanly.
- [ ] Transfer duration inputs accept valid positive integer minute values.
- [ ] Step-free accessibility and bidirectional badges render accurately.
- [ ] Saving updates both datasets atomically in the SQLite backend.
