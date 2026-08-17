# Route Planning Engine — Phased Implementation Roadmap

This document outlines the sequential, small-chunk implementation plan for delivering the **Route Planning Engine** in Travel Assistant. Each chunk is self-contained, testable, and delivers verifiable incremental functionality.

---

## 1. Roadmap Overview & Progressive Complexity

The implementation progresses by increasing levels of algorithmic complexity, delivering a **working visual UI at the very beginning** (Chunk 1) and progressively upgrading the underlying routing algorithms from simple direct routes to multi-modal chains, pruning optimisations, and automated external timetable downloads.

```mermaid
graph TD
    C1[Chunk 1: Foundation & Early Visualisation<br/>(Model + UI with Mock Stub)] --> C2[Chunk 2: Direct Single-Mode Local Routing<br/>(Walk → Single Transit Line → Walk)]
    C2 --> C3[Chunk 3: Multi-Leg & Multi-Modal Local Routing<br/>(Up to 6 Modal Stages, 3 Transfers/Stage)]
    C3 --> C4[Chunk 4: Pruning & Pareto Optimisation<br/>(Last Interchange, Subsumed Detour & Dominance Caps)]
    C4 --> C5[Chunk 5: External Timetable Ingestion (Phase 2)<br/>(BODS / Darwin Gap Bridging & Progressive Enhancement)]
    C5 --> C6[Chunk 6: Background Worker, Sample DB & Runbooks<br/>(Automated Periodic Re-discovery & Production Polish)]
```

---

## 2. Chunk Breakdown & Delivery Sequence

### Chunk 1: Foundation & Early Visualisation (`JourneyRoute` Model + UI with Mock Stub)
- **Objective**: Establish the database storage and delivering working visual route cards in the Web UI immediately using a test stub.
- **Scope & Files**:
  - **Create**: `travel-assistant/app/models/journey_route.py` defining the `JourneyRoute` Peewee model (`id`, `journey_id`, `name`, `auto_generated`, `total_duration_est_minutes`, `transfer_count`, `stages_count`, `primary_mode`, `legs`, `active_days`, `summary_text`).
  - **Modify**: `travel-assistant/app/models/__init__.py` and `travel-assistant/app/db/core.py` to register `JourneyRoute` in `TABLES` and schema initialisation.
  - **Create**: `travel-assistant/app/services/route_planner.py` with an initial stubbed `RoutePlannerService.discover_routes(journey)` returning structured mock multi-modal routes for UI testing.
  - **Modify**: `travel-assistant/app/templates/config_journeys.html` and `travel-assistant/app/static/js/journeys.js`:
    - Add expandable "Discovered Routes" section beneath each journey card.
    - Render visual step pill sequence (e.g. `🚶 8m` $\rightarrow$ `🚌 73 (14m)` $\rightarrow$ `🚶 6m`), total duration, and transfer badges.
    - Add "Re-discover Routes" action button.
  - **Create**: `travel-assistant/app/tests/test_journey_routes.py` and UI test assertions.
- **Prerequisites**: None.
- **Verification & Acceptance Criteria**:
  - `pytest travel-assistant/app/tests/test_journey_routes.py` passes with 100% coverage.
  - Navigating to `/config/journeys` displays clean visual route cards and pills for test journeys.
- **Deliverable**: PR `feat(route-planner): add JourneyRoute model and early route card UI visualisation`.

---

### Chunk 2: Direct Single-Mode Local Routing (Simplest Graph Algorithm)
- **Objective**: Replace the mock discovery stub with real pathfinding for direct single-line journeys (walk $\rightarrow$ direct bus/rail $\rightarrow$ walk, or pure walking) using local database timetables and walking links.
- **Scope & Files**:
  - **Create**: `travel-assistant/app/services/route_graph.py` containing `RouteGraph` and `RouteGraphBuilder` to index stops, walking edges (`walking`), and single-line timetable corridors (`timetables`).
  - **Create**: `travel-assistant/app/services/route_finder.py` implementing direct single-transit-line search (identifying candidate boarding stops within walking distance of origin, alight stops within walking distance of destination, and continuous timetable trips connecting them).
  - **Modify**: `travel-assistant/app/services/route_planner.py` to invoke real direct pathfinding.
  - **Create**: `travel-assistant/app/tests/services/test_direct_routing.py`.
- **Prerequisites**: Chunk 1.
- **Verification & Acceptance Criteria**:
  - `pytest travel-assistant/app/tests/services/test_direct_routing.py` passes.
  - Direct journeys (e.g. Home $\rightarrow$ Work via direct Bus 73, or King's Cross $\rightarrow$ Cambridge via direct rail) correctly discover and persist real route templates from database timetables.
- **Deliverable**: PR `feat(route-planner): implement multi-modal graph builder and direct single-mode pathfinding`.

---

### Chunk 3: Multi-Leg & Multi-Modal Local Routing (Medium Complexity)
- **Objective**: Expand pathfinding to traverse multi-leg connections across distinct modes and interchange transfers in the local database.
- **Scope & Files**:
  - **Modify**: `travel-assistant/app/services/route_graph.py` to index intra-station platform transfers (`platform_transfers`) and inter-stop walking transfers (`walking`).
  - **Modify**: `travel-assistant/app/services/route_finder.py` to implement multi-modal search (Breadth-First Search / constrained $K$-Shortest Paths):
    - Supports up to **6 modal stages** (e.g. `Walk` $\rightarrow$ `Bus Stage` $\rightarrow$ `Rail Stage` $\rightarrow$ `Bus Stage` $\rightarrow$ `Walk`).
    - Supports up to **3 transfers** within any single modal stage (e.g. Bus A $\rightarrow$ Bus B $\rightarrow$ Bus C $\rightarrow$ Bus D).
    - Filters edges by operating day masks (`monday`...`sunday`, `bank_holiday`) matching Journey time settings.
    - Applies geographic corridor bounding (5 km buffer around origin-destination bounding box).
  - **Create**: `travel-assistant/app/tests/services/test_multi_modal_routing.py`.
- **Prerequisites**: Chunk 2.
- **Verification & Acceptance Criteria**:
  - `pytest travel-assistant/app/tests/services/test_multi_modal_routing.py` passes.
  - Correctly discovers composite multi-modal chains (e.g. Walk $\rightarrow$ Bus $\rightarrow$ Transfer $\rightarrow$ Rail $\rightarrow$ Walk) from local database tables.
- **Deliverable**: PR `feat(route-planner): implement multi-modal pathfinding across up to 6 modal stages`.

---

### Chunk 4: Pruning, Deduplication & Optimisation Engine
- **Objective**: Eliminate redundant, illogical, and senseless route variants to produce a clean, non-dominated set of route templates.
- **Scope & Files**:
  - **Create**: `travel-assistant/app/services/route_pruner.py` implementing the 4 formal pruning algorithms:
    1. **Rule 1 (Last Possible Interchange Point)**: Identifies consecutive common stops or transferable stop pairs between two lines and strictly selects the furthest common interchange point.
    2. **Rule 2 (Subsumed Detour Elimination)**: Discards candidate routes that disembark and re-board an existing continuous service unnecessarily.
    3. **Rule 3 (Pareto-Frontier Dominance)**: Discards routes that are strictly dominated in duration and transfer count across all active time windows.
    4. **Rule 4 (Senseless Detour Threshold)**: Prunes candidate routes exceeding $1.5\times$ or $+30$ minutes over the fastest alternative.
  - **Modify**: `travel-assistant/app/services/route_planner.py` to pipeline discovered candidate routes through `RoutePruner`.
  - **Create**: `travel-assistant/app/tests/services/test_route_pruner.py`.
- **Prerequisites**: Chunk 3.
- **Verification & Acceptance Criteria**:
  - `pytest travel-assistant/app/tests/services/test_route_pruner.py` passes.
  - Overlapping routes (Route 1 [A, B, C, D, E] and Route 2 [C, D, E, F, G]) generate exactly 1 route template changing at Stop E.
- **Deliverable**: PR `feat(route-planner): implement Last-Possible Interchange pruning and Pareto dominance optimisation`.

---

### Chunk 5: External Intermediate Timetable Ingestion (Phase 2) & Progressive Enhancement
- **Objective**: Automatically detect corridor gaps and fetch missing intermediate bus/rail timetables from BODS and Darwin S3, progressively enhancing journeys as new data arrives.
- **Scope & Files**:
  - **Create**: `travel-assistant/app/services/route_ingestion.py`:
    - Identifies forward reach frontier ($\mathcal{I}_{\text{orig}}$) and reverse reach frontier ($\mathcal{I}_{\text{dest}}$).
    - Queries `BodsClient` for published bus routes serving intermediate stops in the corridor.
    - Queries `TrainS3Client` / Darwin for rail connections between intermediate stations.
    - Ingests up to 3 candidate timetables with `auto_added=True`.
    - Automatically discovers and inserts intermediate walking transfer links.
    - **Progressive Enhancement**: When new timetables are synchronised or when initial network errors clear, re-discovery smoothly updates and enhances stored journey routes.
    - **Graceful Fallback**: Returns locally discovered routes from Phase 1 if external API calls time out or fail.
  - **Create**: `travel-assistant/app/tests/services/test_route_ingestion.py`.
- **Prerequisites**: Chunk 4.
- **Verification & Acceptance Criteria**:
  - `pytest travel-assistant/app/tests/services/test_route_ingestion.py` passes.
  - Disconnected origin and destination endpoints trigger intermediate timetable download and successfully discover a bridging route.
- **Deliverable**: PR `feat(route-planner): implement Phase 2 intermediate timetable gap ingestion and progressive enhancement`.

---

### Chunk 6: Background Sync, Sample DB Seeding & Production Polish
- **Objective**: Complete end-to-end automation with background worker re-discovery, realistic sample dataset seeding, automated browser UI test scenarios, and documentation.
- **Scope & Files**:
  - **Modify**: `travel-assistant/app/sync/worker.py` to trigger periodic background route re-discovery for journeys older than 24 hours.
  - **Modify**: `travel-assistant/app/views/config/journeys.py` to trigger asynchronous route discovery automatically on journey save/edit.
  - **Modify**: `scripts/seed_sample_db.py` to seed realistic discovered `JourneyRoute` records for the 4 sample journeys.
  - **Modify**: `docs/testing/05_journeys.md` with step-by-step testing runbooks for route cards and on-demand re-discovery.
  - **Modify**: `travel-assistant/DOCS.md` and `travel-assistant/CHANGELOG.md`.
  - **Verify**: Run full verification suite `bash scripts/verify_all.sh`.
- **Prerequisites**: Chunk 5.
- **Verification & Acceptance Criteria**:
  - `bash scripts/run_dev.sh --sample-db` starts up with populated route cards for all seeded journeys.
  - `bash scripts/verify_all.sh` passes with 0 lint warnings and 100% test success.
- **Deliverable**: PR `feat(route-planner): add background sync automation, sample database seeding, and UI test runbooks`.

---

## 3. Summary Schedule

| Chunk | Milestone Focus | Algorithmic Complexity | User-Visible Output |
| :--- | :--- | :--- | :--- |
| **Chunk 1** | Model + Early Visualisation | Baseline | Route cards, visual step pills, mock stub |
| **Chunk 2** | Direct Single-Mode Routing | Low | Real direct bus/train/walk route templates |
| **Chunk 3** | Multi-Leg & Multi-Modal Routing | Medium | Composite Walk $\rightarrow$ Bus $\rightarrow$ Rail $\rightarrow$ Walk chains |
| **Chunk 4** | Pruning & Pareto Optimisation | Medium–High | Last-interchange pruning, senseless detour elimination |
| **Chunk 5** | External Gap Timetable Ingestion | High | Automated BODS/Darwin downloads, progressive enhancement |
| **Chunk 6** | Automation, Sample DB & Runbooks | Integration | Daily background sync, sample DB, docs |
