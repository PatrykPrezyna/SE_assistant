# Spec 0001: Embedded Assistant Chat

**Status:** Draft  
**Author:** System  
**Date:** 2026-11-28

## Summary

Integrate the SE assistant chat (currently `python -m assistant`) into the System Explorer web application, so users access both the model viewer and AI chat in one interface.

## User Stories

1. **As a user**, I want to see a chat panel in the System Explorer viewer, so I can interact with the AI assistant without switching applications.

2. **As a hosted user**, I want assistant-created .sysml files to be committed and pushed (like manual edits), so the team sees AI changes in git.

3. **As an admin**, I want to configure the assistant with environment variables (OpenAI-compatible API), so I can use any provider without code changes.

4. **As a user**, I want a clear message when the assistant is not configured, so the explorer still works without AI features.

## Acceptance Criteria

### UI
- [ ] Chat panel visible in viewer (collapsible side panel or similar)
- [ ] Panel uses vanilla JS, consistent with current viewer styling
- [ ] Panel shows "assistant not configured" when env vars are missing
- [ ] Panel works in both local and hosted modes

### Backend
- [ ] Assistant API routes mounted in explorer server (`/api/session`, `/api/chat`)
- [ ] Routes work in local mode (same as today)
- [ ] Routes work in hosted mode (GitHub session auth)
- [ ] Auth: hosted requires GitHub login, local uses Basic Auth if configured
- [ ] Stdlib-only core preserved (no new dependencies)

### Model Integration
- [ ] Assistant-written .sysml files land in the explorer's model folder
- [ ] In hosted mode: files committed and pushed (authored as signed-in user)
- [ ] Viewer refreshes to show new/updated elements

### Configuration
- [ ] `ASSISTANT_BASE_URL` - provider endpoint (OpenAI-compatible)
- [ ] `ASSISTANT_API_KEY` - provider key
- [ ] `ASSISTANT_MODEL` - model name
- [ ] All env-driven, no hardcoded providers
- [ ] Standard OpenAI `/chat/completions` format

### Documentation & Testing
- [ ] `render.yaml` updated with assistant env vars
- [ ] `README.md` and `FEATURES.md` updated
- [ ] Tests for assistant routes, auth, hosted commits, disabled mode
- [ ] Existing tests pass, CI green

## Design

### UI Placement
A collapsible side panel on the right side of the viewer:
- Toggle button in toolbar ("Chat" or icon)
- Panel slides in/out, doesn't obscure the diagram when open
- Contains: message list + input field
- Same styling as the rest of the viewer (borders, colors, fonts)

### API Routes
Mount in both `app.py` (local) and `cloud.py` (hosted):
- `GET /api/session` - initial state, greeting, config status
- `POST /api/chat` - send messages, receive assistant reply
- Both require auth in hosted mode (GitHub session)
- Both use Basic Auth in local mode if configured

### Code Structure
- Keep `src/assistant/` modules as-is (agent, provider, tools, config)
- Extend `app.py` / `cloud.py` to mount assistant routes
- Create `src/system_explorer/assistant_panel.js` and `.css` for UI
- Update `viewer.html` to include the panel + scripts

### Model Writes (Hosted Mode)
When assistant calls `stakeholder_apply` and writes .sysml files:
- Use `CloudContext.sync.commit_and_push()` (same as View saves)
- Author: the signed-in user (`request_user` from session)
- Message: "Assistant: update model from stakeholder register"
- Viewer polls/refreshes to show changes (existing mechanism)

### Fallback
If `ASSISTANT_BASE_URL` or `ASSISTANT_MODEL` are unset:
- `/api/session` returns `configured: false` with a message
- UI shows "Assistant not configured. Set ASSISTANT_BASE_URL and ASSISTANT_MODEL."
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
