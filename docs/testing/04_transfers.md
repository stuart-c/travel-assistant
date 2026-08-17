# Test Scenario 04: Platform & Stand Transfers

## Objective
Validate the configuration of intra-station platform and bus stand interchange transfer durations with step-free accessibility flags. (Inter-location walking connections are handled by the Walking feature).

## Preconditions
1. Development server running: `bash scripts/run_dev.sh --sample-db`
2. Target URL: `http://localhost:8099/config/transfers`
3. Antigravity `/browser` agent active.

---

## Test Steps

### Scenario 4.1: Platform & Stand Transfers Table
1. Navigate to `http://localhost:8099/config/transfers`.
2. Verify page title is `Transfers - Travel Assistant`.
3. Verify that the **Platform & Stand Transfers** table is presented.
4. Verify seeded platform transfers render in the table:
   * **London King's Cross Platform 1 to Platform 8** (4 minutes, Step-Free badge `✓`, Bidirectional badge `⇄`).

### Scenario 4.2: Adding a Platform Interchange Transfer
1. Click **+ Add Platform Transfer**.
2. In the modal dialogue, configure:
   * **Station**: Search and select `London Euston`.
   * **From Platform**: `1`
   * **To Platform**: `8`
   * **Transfer Duration**: `3` minutes.
   * **Bidirectional**: Checked (`Yes`).
   * **Step-Free**: Checked (`Yes`).
   * **Interchange Notes**: `Use the central footbridge or ramp.`
3. Click **Save Transfer**.
4. Verify the row appears in the Platform Transfers table.
5. Click **Save Changes** in the header action bar.
6. **Expected Result**:
   * Flash confirmation: `Transfers saved successfully.`
   * Platform transfer persists with 3 minutes duration and step-free indicator upon page reload.

---

## Acceptance Criteria
- [ ] Platform & Stand Transfers table mounts and renders data cleanly.
- [ ] Transfer duration inputs accept valid positive integer minute values.
- [ ] Step-free accessibility and bidirectional badges render accurately.
- [ ] Saving updates platform transfers atomically in the SQLite backend.

