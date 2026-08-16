# Test Scenario 03: Timetables & Operating Schedules

## Objective
Validate schedule creation, operating day-of-week selection toggles, date validity constraints, transport type assignment, and Grid.js interactive schedule persistence.

## Preconditions
1. Development server running: `bash scripts/run_dev.sh --sample-db`
2. Target URL: `http://localhost:8099/config/timetables`
3. Antigravity `/browser` agent active.

---

## Test Steps

### Scenario 3.1: Table Initialisation & Existing Schedules
1. Navigate to `http://localhost:8099/config/timetables`.
2. Verify page title is `Timetables - Travel Assistant`.
3. Check that pre-seeded schedules render in Grid.js:
   * **Weekday Morning Commute** (Rail, Mon-Fri active, Sat-Sun inactive).
   * **Weekend Leisure Schedule** (Bus, Sat-Sun active, Mon-Fri inactive).
4. Verify operating days badges (e.g., `M T W T F` highlighted, `S S` dimmed).

### Scenario 3.2: Creating a Custom Timetable Schedule
1. Click the **+ Add Timetable** button.
2. In the modal dialogue, enter:
   * **Timetable Name**: `Night Bus Service`
   * **Transport Mode**: Select `Bus` from the dropdown.
   * **Start Date**: `2026-09-01`
   * **End Date**: `2026-12-31`
   * **Operating Days**: Check `Friday`, `Saturday`, `Sunday`, `Bank Holidays`. Uncheck `Mon`, `Tue`, `Wed`, `Thu`.
3. Click **Add to Table**.
4. Verify that `Night Bus Service` appears in the Grid.js table.
5. Click **Save Changes** in the bottom action bar.
6. **Expected Result**:
   * Flash confirmation: `Timetables saved successfully.`
   * New timetable displays in the table with proper active day indicators upon page refresh.

### Scenario 3.3: Date Range Constraint Validation
1. Click **+ Add Timetable**.
2. Enter Name: `Invalid Date Range Schedule`.
3. Set **Start Date**: `2026-12-31`.
4. Set **End Date**: `2026-01-01` (End date earlier than Start date).
5. Attempt to add or submit the form.
6. **Expected Result**:
   * Validation warning prevents submission, explaining that end date cannot precede start date.

---

## Acceptance Criteria
- [ ] Operating schedule grid displays active/inactive days with distinct visual styling.
- [ ] Adding, editing, and removing timetables updates the client-side table state.
- [ ] Form submission correctly persists timetable records and JSON grid contents.
