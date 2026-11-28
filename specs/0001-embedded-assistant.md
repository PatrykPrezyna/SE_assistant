# Spec 0001: Embedded Assistant Chat

**Status:** Implemented  
**Author:** System  
**Date:** 2026-11-28  
**Updated:** 2026-11-28 (Chat actually reaches the provider; panel ships in the package)

## Summary

Integrate the SE assistant chat into the System Explorer web application with conversational modeling: the assistant asks clarifying questions, then applies structured edits to the model following existing conventions. Users see changes in real-time without page reloads.

## User Stories

1. **As a user**, I want to see a chat panel in the System Explorer viewer, so I can interact with the AI assistant without switching applications.

2. **As a hosted user**, I want assistant-created .sysml files to be committed and pushed (like manual edits), so the team sees AI changes in git.

3. **As an admin**, I want to configure the assistant with environment variables (OpenAI-compatible API), so I can use any provider without code changes.

4. **As a user**, I want a clear message when the assistant is not configured, so the explorer still works without AI features.

## Acceptance Criteria

### UI
- [x] Chat panel visible in viewer (slide-in side panel from right)
- [x] Modern message bubbles: blue gradient (user), light gray (assistant)
- [x] Markdown rendering in assistant messages
- [x] Empty state with example prompts ("Add a stakeholder", "Add a nurse", etc.)
- [x] Enter sends, Shift+Enter adds newline
- [x] Send button disabled while thinking
- [x] Panel shows "assistant not configured" with clear message when env vars missing
- [x] Panel works in both local and hosted modes

### Backend - API Routes
- [x] `/api/session` and `/api/chat` mounted in explorer server
- [x] Routes work in local mode with optional Basic Auth
- [x] Routes work in hosted mode with GitHub session auth
- [x] Same-origin `fetch` sends the session cookie (that is the default; no extra option)
- [x] Panel JavaScript and CSS are package data, so a `pip install` serves them
- [x] Chat reads the tool's methodology file, not a file inside the model repo
- [x] A failure in the chat handler is a JSON error in the panel, not a dropped connection
- [x] Stdlib-only core preserved (no new dependencies)

### Error Handling
- [x] All backend errors displayed as readable messages in chat (no silent failures)
- [x] Network errors shown with descriptive text
- [x] HTTP status codes handled (401, 503, etc.)
- [x] Configuration errors explained
- [x] Provider errors logged server-side

### Model Integration - Conversational Flow
- [x] **Clarify-then-apply:** Assistant asks questions before creating elements
- [x] **Structured edits:** `add_model_element` tool for creating SysML
- [x] **Follows conventions:** Stakeholders are `part def` (not `actor def`), placed in Context file
- [x] **Valid SysML:** UpperCamelCase names, proper doc comments
- [x] **Real-time refresh:** New definitions are added to the open view (context elements on the context view) and fitted, without a reload
- [x] Assistant-written .sysml files land in the explorer's model folder
- [x] In hosted mode: files committed and pushed (authored as signed-in user)

### Configuration
- [x] `ASSISTANT_BASE_URL` - provider endpoint (OpenAI-compatible)
- [x] `ASSISTANT_API_KEY` - provider key
- [x] `ASSISTANT_MODEL` - model name
- [x] All env-driven, works in both local and hosted modes
- [x] Standard OpenAI `/chat/completions` format

### Documentation & Testing
- [x] Tests for assistant routes, auth, error handling
- [x] Tests for `add_model_element` tool with model conventions
- [x] Tests for hosted commit path with proper authorship
- [x] Tests pass (`python tests/test_system_explorer.py`)

## Design

### UI
A collapsible side panel (right side, 400px) in the same type and colors as the explorer toolbar. The zoom controls move out from under it while it is open.
- User messages: solid blue, right aligned
- Assistant messages: white cards, markdown
- Errors: a full-width message in the transcript. The thinking row is removed when the request ends
- Suggestion chips under the greeting, including "Add a nurse to the context"
- Enter sends, Shift+Enter adds a newline

### API Routes
Mount via `make_handler(folder, layout_path, cloud, assistant_settings)`:
- `GET /api/session` - initial state, greeting, config status
- `POST /api/chat` - send messages, receive assistant reply

**Auth in hosted mode (GitHub session):**
- `_check_assistant_auth()` checks `self.user is not None`
- `self.user` is set by `_gate()` from the GitHub session cookie
- A same-origin `fetch` sends that cookie. Adding `credentials: 'same-origin'` changes nothing; it is already the default
- If the server is running with anonymous access, the assistant is open too. The page gate already allowed the request

**Why hosted chat did nothing (verified against Parley and the running server):**
1. `assistant_panel.js` / `assistant_panel.css` were not in the wheel. The Docker image runs `pip install .`, so the deployed page referenced assets that 404. The Chat control had no script.
2. Local and hosted mode pointed `ASSISTANT_METHODOLOGY` at `<model folder>/methodology/product-development.yaml`. The model repo does not contain that file. `system_message` raised `FileNotFoundError` before any provider call. The handler did not catch it, so the socket closed. The panel showed "Network error: Failed to fetch" and left "Thinking…" on screen.
3. Parley accepts the tool schema. A plain completion and a completion that includes the tools both return a normal message. The provider was not the failure.
4. `loadModel()` reparses the files but a View only draws ids already in `elements`. A new `part def` stayed off the diagram until it was added to the view.

**Auth in local mode:**
- Optional Basic Auth if `ASSISTANT_AUTH_USER` / `ASSISTANT_AUTH_PASSWORD` set
- Otherwise open access

### Conversational Modeling Flow

**1. User makes request:** "Add a nurse to the context"

**2. Assistant clarifies if needed:**
- "What role does the nurse play?"
- "Which use cases involve them?"
- "What are their main concerns?"

**3. Assistant applies structured edit:**
```javascript
{
  "tool": "add_model_element",
  "arguments": {
    "element_type": "stakeholder",  // Creates part def
    "name": "Nurse",
    "description": "Healthcare professional who administers medication..."
  }
}
```

**4. Tool execution:**
- Validates name (UpperCamelCase)
- Checks for duplicates
- Creates `part def Nurse` in `*Context.sysml` file
- Returns confirmation message

**5. Real-time update:**
- JS detects a tool note mentioning "model" or "sysml"
- Calls `refreshAfterAssistantEdit()`, which reparses and adds the new definitions to the view
- A new context element is shown on the context view, fitted into the camera, and saved
- Assistant shows confirmation in the chat. The thinking indicator is cleared before that paint

### Model Conventions

**Stakeholders (people):**
- Created as `part def` (NOT `actor def`)
- Placed in `*Context.sysml` file
- Example: `part def Nurse { doc /* Healthcare professional... */ }`
- Later used as `actor` or `subject` in use cases

**Following spine-cooling-model pattern:**
```sysml
package CoolSpineSystemContext {
    part def Nurse {
        doc /*
        Healthcare professional who administers medication and monitors
        patient vitals during therapeutic cooling procedures.
        */
    }
}
```

### Code Structure
- `src/assistant/agent.py` - tools array, includes `add_model_element`
- `src/assistant/tools.py` - `_add_model_element()` implementation
- `src/system_explorer/app.py` - `make_handler()` mounts routes
- `src/system_explorer/assistant_panel.js` - UI logic, **sends cookies**
- `src/system_explorer/assistant_panel.css` - modern styling

### Model Writes (Hosted Mode)
When assistant edits model:
- Tool writes to `.sysml` files in `model_folder`
- `do_POST` detects notes in response
- Calls `cloud.sync.commit_and_push(sysml_files, message, self.user)`
- Commit authored as signed-in GitHub user
- Push happens in background (1s batching)

### Error Display
All errors visible in chat:
- 401: "Please sign in"
- 503: "Assistant module not available"
- Network errors: "Network error: [message]"
- Provider errors: Logged server-side, shown in chat
- Configuration errors: "Set ASSISTANT_BASE_URL and ASSISTANT_MODEL"

### Fallback
If `ASSISTANT_BASE_URL` or `ASSISTANT_MODEL` are unset:
- `/api/session` returns `configured: false` with message
- UI shows clear instructions in yellow banner
- Explorer continues to work normally

## Non-Goals
- **Not implementing:** swimlane/use-case features (keep scope tight)
- **Not refactoring:** existing explorer or assistant code
- **Not removing:** standalone `python -m assistant` (may stay for local dev)

## Migration
On Render, after deploying this PR:
1. Add env vars to `system-explorer` service:
   - `ASSISTANT_BASE_URL` (e.g. `https://api.openai.com/v1`)
   - `ASSISTANT_API_KEY` (sync: false)
   - `ASSISTANT_MODEL` (e.g. `gpt-4`)
2. Retire the separate `se-assistant` service
3. Users access chat at the existing explorer URL

## Risks & Mitigations
- **Risk:** Auth mismatch (GitHub session vs. Basic Auth confusion)
  - **Mitigation:** Clear auth checks in both modes, tests for each
- **Risk:** Assistant writes breaking git sync
  - **Mitigation:** Reuse existing commit/push logic, test commits
- **Risk:** UI clutter
  - **Mitigation:** Collapsible panel, hidden by default

## Open Questions
- None (design is clear)

## References
- PR #3 (branch `cursor/render-deployment-main-base-a505`): env config, /healthz, Basic Auth
- Existing hosted mode: `src/system_explorer/cloud.py`
- Assistant server: `src/assistant/server.py`
