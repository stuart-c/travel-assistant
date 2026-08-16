# Test Scenario 01: API Credentials & Asynchronous Validation

## Objective
Validate the API credentials configuration page, secure token persistence, and asynchronous credential validation feedback badges across all external transport data providers.

## Preconditions
1. Development server running: `bash scripts/run_dev.sh --sample-db`
2. Target URL: `http://localhost:8099/config/credentials`
3. Antigravity `/browser` agent active.

---

## Test Steps

### Scenario 1.1: Initial View & Credential Fields Layout
1. Navigate to `http://localhost:8099/config/credentials`.
2. Verify page title displays `API Credentials - Travel Assistant`.
3. Verify the presence of service sections:
   * **Department for Transport (DfT) Bus Open Data Service (BODS)**: API key input and "Validate Bus API" button.
   * **National Rail Darwin Timetables (S3 Bucket)**: S3 Bucket name, AWS Access Key ID, AWS Secret Access Key, AWS Region, and "Validate S3 Bucket" button.
   * **National Rail Darwin Live Arrivals (OpenLDBWS)**: Live API Token, Endpoint URL, and "Validate Live API" button.
   * **OpenAI Integration**: API Key, Base URL, Model selector (default `gpt-4o-mini`), and "Validate OpenAI" button.
   * **Google Maps**: API Key, Region code (default `uk`), and "Validate Google Maps" button.
4. Verify all sensitive token fields (`type="password"`) mask user inputs.

### Scenario 1.2: Asynchronous Validation Feedback (Error State)
1. In the **Bus Open Data Service** section, enter `invalid-test-token-xyz` into the API key field.
2. Click the **Validate Bus API** button.
3. **Expected Result**:
   * A loading indicator appears briefly.
   * A failure status badge/toast appears with an explanatory message (e.g., `Invalid Bus API key or unauthorised access (HTTP 403)`).
   * No full page reload occurs (handled asynchronously via AJAX).

### Scenario 1.3: Credential Persistence (Form Save)
1. Update the **Google Maps Region** to `uk` and **OpenAI Model** to `gpt-4o-mini`.
2. Click the primary **Save API Credentials** button at the bottom of the form.
3. **Expected Result**:
   * The form submits with HTTP 303 redirection.
   * A success banner appears: `API credentials saved successfully.`
   * Form inputs retain the saved values upon subsequent page load.

---

## Acceptance Criteria
- [ ] All 5 transport service sections render cleanly without CSS alignment issues.
- [ ] Async validation buttons provide instant visual feedback without navigating away.
- [ ] Form submission saves values to SQLite database and displays a flash notification.
- [ ] All UI labels and messages use British English (`unauthorised`, `initialise`, `colour`).
