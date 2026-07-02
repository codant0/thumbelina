# LLM Endpoint Management — Frontend Design

> **Date:** 2026-07-02  
> **Scope:** React UI for managing multiple LLM base URLs, fetching model lists, and running speed tests.  
> **Strategy:** Start with OpenAI / OpenAI-compatible providers; build components so Ollama and Anthropic can reuse the same UI later.

---

## 1. Goal

Extend the Settings page so users can:

1. Save multiple LLM endpoints (base URLs) per provider.
2. Pull available model names from an endpoint after entering an API key.
3. Run a one-click latency / availability test on any saved endpoint.
4. Mark a default endpoint so the main LLM form can prefill `base_url`.

The first implementation targets **OpenAI-compatible endpoints**. Ollama and Anthropic will reuse the same components once their backend providers are implemented.

---

## 2. Architecture Overview

```
┌────────────────────────────────────────────────────────────────┐
│  SettingsPanel.tsx                                             │
│  ├── LLMConfigCard (existing provider/model/base_url/api_key)  │
│  ├── EndpointManager.tsx  ← new                                │
│  │   ├── EndpointList.tsx                                      │
│  │   ├── EndpointForm.tsx                                      │
│  │   └── SpeedTestResult.tsx                                   │
│  └── ModelSelector.tsx  ← new (integrated into LLMConfigCard)  │
└────────────────────┬───────────────────────────────────────────┘
                     │ fetch()
┌────────────────────▼───────────────────────────────────────────┐
│  api/llmConfig.ts                                              │
│  - fetchEndpoints()                                            │
│  - createEndpoint()                                            │
│  - updateEndpoint()                                            │
│  - deleteEndpoint()                                            │
│  - runSpeedTest()                                              │
│  - fetchModels()                                               │
└────────────────────────────────────────────────────────────────┘
```

---

## 3. Data Model

### 3.1 `LLMEndpoint`

Matches the backend `LLMEndpointResponse` schema one-to-one.

```typescript
interface LLMEndpoint {
  id: string
  provider: 'openai' | 'ollama' | 'anthropic'
  name: string
  base_url: string
  api_key_set: boolean
  is_default: boolean
  last_latency_ms?: number
  last_total_ms?: number
  is_reachable?: boolean
  last_tested_at?: string // ISO 8601
}
```

### 3.2 `SpeedTestResult`

Matches the backend `SpeedTestResponse` schema.

```typescript
interface SpeedTestResult {
  endpoint_id: string
  reachable: boolean
  latency_ms?: number
  total_ms?: number
  error?: string
}
```

### 3.3 `ModelList`

```typescript
interface ModelList {
  provider: string
  base_url: string
  models: string[]
}
```

### 3.4 Form state

```typescript
interface EndpointFormData {
  provider: 'openai' | 'ollama' | 'anthropic'
  name: string
  base_url: string
  api_key: string
  is_default: boolean
}
```

---

## 4. Components and Responsibilities

### 4.1 `api/llmConfig.ts`

A thin fetch wrapper. All Settings-related LLM config calls live here for testability and reuse.

```typescript
export async function fetchEndpoints(provider?: string): Promise<LLMEndpoint[]>
export async function createEndpoint(data: EndpointFormData): Promise<LLMEndpoint>
export async function updateEndpoint(id: string, data: Partial<EndpointFormData>): Promise<LLMEndpoint>
export async function deleteEndpoint(id: string): Promise<void>
export async function runSpeedTest(id: string): Promise<SpeedTestResult>
export async function fetchModels(params: { provider: string; base_url: string; api_key?: string }): Promise<ModelList>
```

Rules:
- Reuse the existing `fetch` base path (`/api/v1`).
- `api_key` is sent only on write; it is never rendered after save.
- Convert HTTP errors into `Error` with the backend `detail` message.

### 4.2 `EndpointManager.tsx`

Container component that owns endpoint list state.

Responsibilities:
- Load endpoints on mount.
- Open / close the create/edit form.
- Handle create, update, delete, speed test, and set-default actions.
- Show global feedback via the existing `message` / `isError` banner in `SettingsPanel` (passed in as props).

Props:

```typescript
interface EndpointManagerProps {
  onMessage: (message: string, isError: boolean) => void
}
```

### 4.3 `EndpointList.tsx`

Pure presentational component.

Responsibilities:
- Render endpoints as cards or table rows.
- Display provider badge, name, base_url, reachability status, last latency.
- Emit events: edit, delete, speed-test, set-default.

Columns / fields shown:
- Name (bold)
- Provider badge
- Base URL (truncated with `title` tooltip)
- Default star / badge
- Last tested: relative time or “Never”
- Latency: `123 ms` or `—`
- Reachable: green dot / red dot / gray dot
- Actions: Speed test, Edit, Delete, Set default

### 4.4 `EndpointForm.tsx`

Modal or inline form for creating / editing an endpoint.

Fields:
- Provider select (`openai` only in first iteration; options commented / disabled for future providers)
- Name input
- Base URL input (placeholder: `https://api.openai.com/v1`)
- API key input (password; optional label “Leave empty to keep current key” when editing)
- “Set as default” checkbox

Validation:
- `base_url` must be a valid URL.
- `name` non-empty.
- `provider` non-empty.

On submit, call `createEndpoint` or `updateEndpoint`, then close and refresh list.

### 4.5 `SpeedTestResult.tsx`

Small inline component to render a single speed test outcome.

States:
- Loading: spinner + “Testing…”
- Success: green check + `123 ms` (latency) + `245 ms` (total)
- Error: red cross + error message truncated

### 4.6 `ModelSelector.tsx`

Integrates into the existing `LLMConfigCard` section, next to the Model input.

Responsibilities:
- Accept current `provider`, `base_url`, and `api_key`.
- Provide a “Fetch models” button.
- On click, call `fetchModels` and show a dropdown / datalist of returned model IDs.
- When user selects a model, update the parent `model` state.

UI options considered:
- **A.** Replace model input with a select once models are fetched.
- **B.** Keep model input free-text, show a datalist populated from fetched models.
- **Decision: B.** Keeps flexibility (user can still type a model name not in the list) while offering convenience.

### 4.7 `LLMConfigCard` modifications

The existing `SettingsPanel.tsx` LLM section becomes `LLMConfigCard` (or stays inline if small).

Changes:
- Add `<ModelSelector />` under the Model input.
- Optionally display the current default endpoint’s `base_url` as a hint when `base_url` is empty.
- No breaking changes to `PUT /config/llm` payload.

---

## 5. Data Flow

### 5.1 Loading endpoints

1. `EndpointManager` mounts.
2. Calls `fetchEndpoints()`.
3. Stores result in `endpoints` state.
4. `EndpointList` renders.

### 5.2 Creating an endpoint

1. User clicks “Add endpoint”.
2. `EndpointForm` opens with empty state.
3. User fills form and submits.
4. `EndpointManager` calls `createEndpoint(data)`.
5. On success, refresh list and show success message.
6. On error, show error message.

### 5.3 Speed test

1. User clicks speed-test icon on an endpoint row.
2. `EndpointManager` sets `testingId` state.
3. Calls `runSpeedTest(id)`.
4. Updates local endpoint record with returned `latency_ms`, `total_ms`, `is_reachable`, `last_tested_at`.
5. `EndpointList` re-renders with new status.

### 5.4 Fetching model list

1. User enters base_url and api_key in main LLM form.
2. Clicks “Fetch models” next to Model input.
3. `ModelSelector` calls `fetchModels({ provider, base_url, api_key })`.
4. On success, populate `<datalist id="model-options">`.
5. User can pick from list or continue typing freely.

---

## 6. Error Handling

| Scenario | UX |
|---|---|
| Network error | Red banner: “Network error. Please check your connection.” |
| Endpoint unreachable | Red banner: “Failed to reach endpoint: <detail>” |
| Provider not supported | Disable “Fetch models” button with tooltip “Model listing not supported for this provider yet.” |
| Validation error (invalid URL) | Inline field error, prevent submit |
| Speed test failed | Red inline result: “Unreachable — <reason>” |

All errors are surfaced through `onMessage` for full-page feedback or inline for form/speed-test specific errors.

---

## 7. Testing Strategy

### 7.1 API client tests

`frontend/src/api/llmConfig.test.ts`:
- Mock `fetch`.
- Test each function returns typed data.
- Test error handling extracts `detail`.
- Test `api_key` is included in body when provided.

### 7.2 Component tests

`frontend/src/components/Settings/EndpointManager.test.tsx`:
- Renders loading state.
- Renders endpoint list after fetch.
- Opens form on “Add endpoint”.
- Calls API and refreshes list after create.
- Calls API and updates row after speed test.

`frontend/src/components/Settings/EndpointForm.test.tsx`:
- Validates required fields.
- Submits correct payload.
- Shows “keep current key” hint when editing.

`frontend/src/components/Settings/ModelSelector.test.tsx`:
- Fetches models on button click.
- Populates datalist.
- Calls parent on selection.

### 7.3 Contract tests

- Verify `LLMEndpoint` interface field names match the backend `LLMEndpointResponse` schema defined in the companion backend design doc.

---

## 8. Styling

Reuse existing CSS variables and classes from the project:

- `--success`, `--error`, `--warning`, `--text-secondary`
- `.card`, `.card-title`, `.form-group`, `.form-label`, `.form-input`, `.form-select`, `.btn`, `.btn-primary`, `.btn-ghost`, `.btn-danger`

New classes (if needed):
- `.endpoint-list` — grid / flex layout for rows
- `.endpoint-badge` — provider badge
- `.endpoint-status-dot` — reachable indicator

Keep the visual style consistent with the existing Settings panel.

---

## 9. Files to Create / Modify

### Create
- `frontend/src/api/llmConfig.ts`
- `frontend/src/api/llmConfig.test.ts`
- `frontend/src/components/Settings/EndpointManager.tsx`
- `frontend/src/components/Settings/EndpointManager.test.tsx`
- `frontend/src/components/Settings/EndpointList.tsx`
- `frontend/src/components/Settings/EndpointForm.tsx`
- `frontend/src/components/Settings/EndpointForm.test.tsx`
- `frontend/src/components/Settings/SpeedTestResult.tsx`
- `frontend/src/components/Settings/ModelSelector.tsx`
- `frontend/src/components/Settings/ModelSelector.test.tsx`

### Modify
- `frontend/src/components/Settings/SettingsPanel.tsx` — integrate `EndpointManager` and `ModelSelector`, lift message state.
- `frontend/src/components/Settings/SettingsPanel.test.tsx` — update tests for new sections.

---

## 10. Consistency with Backend Design

| Frontend | Backend | Contract |
|---|---|---|
| `LLMEndpoint.id` | `LLMEndpointResponse.id` | UUID string |
| `LLMEndpoint.provider` | `LLMEndpointResponse.provider` | string, enum later |
| `LLMEndpoint.base_url` | `LLMEndpointResponse.base_url` | URL string |
| `LLMEndpoint.api_key_set` | `LLMEndpointResponse.api_key_set` | boolean |
| `LLMEndpoint.is_default` | `LLMEndpointResponse.is_default` | boolean |
| `LLMEndpoint.last_latency_ms` | `LLMEndpointResponse.last_latency_ms` | integer or null |
| `LLMEndpoint.last_total_ms` | `LLMEndpointResponse.last_total_ms` | integer or null |
| `LLMEndpoint.is_reachable` | `LLMEndpointResponse.is_reachable` | boolean or null |
| `LLMEndpoint.last_tested_at` | `LLMEndpointResponse.last_tested_at` | ISO 8601 string or null |
| `ModelList.models` | `ModelListResponse.models` | list of strings |
| `SpeedTestResult.latency_ms` | `SpeedTestResponse.latency_ms` | integer or null |
| `SpeedTestResult.total_ms` | `SpeedTestResponse.total_ms` | integer or null |

Both documents share the same endpoint paths and payload shapes. The backend doc is the source of truth for API schema; this doc is the source of truth for UI state and component behavior.

---

## 11. Open Questions

1. Should the UI allow renaming / deleting the currently active endpoint (the one used by `PUT /config/llm`)? (Yes, with no special guard; active config is independent of endpoint catalog.)
2. Should fetching models auto-save the endpoint if it does not exist? (No; model fetching is exploratory. Saving is explicit.)
3. Should speed-test results be cached in backend only, or also mirrored in frontend local state? (Backend is source of truth; frontend can optimistically update local row for responsiveness.)
