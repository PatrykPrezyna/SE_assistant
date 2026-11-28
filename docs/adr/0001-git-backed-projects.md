# ADR 0001: Keep projects in the git repo, one folder each

**Status:** Accepted
**Date:** 2026-11-28

## Context

System Explorer on Render's free plan has no durable disk. The container
clones `GITHUB_REPO` (today `PatrykPrezyna/spine-cooling-model`,
`MODEL_PATH=.`) and the clone is thrown away on every restart. The only
store that survives is a commit pushed back to that repo. `GitSync` in
`cloud.py` already does that for Views and `layout.json`.

The deployment currently serves the `.sysml` files at the repo root, so
every login opens the spine-cooling model. New work needs a place to live
that does not delete or rewrite those files. A database, Render Disk, or
a second repository would be a new service. The free web service cannot
rely on local files.

Local mode has a real disk, but it should use the same project layout so
the two modes do not diverge.

## Decision

The cloned repo is a **workspace**. Each project is a directory:

```
<MODEL_PATH>/projects/<id>/
    project.json
    NewProject.sysml
    NewProjectContext.sysml
    views/
    layout.json
```

`<id>` is a lowercase token (`p` + time + a short random suffix). The
server commits only files under `projects/<id>/`, with the same
`commit_and_push` path used for View saves, authored as the signed-in
user when there is one.

The active project is not stored in git. It is the `sx_project` cookie,
so two people can work on two projects without one login overwriting the
other's "current" pointer. A missing cookie on login means "create a
project", not "open whatever was committed last".

Files that already live in the workspace root, including every
spine-cooling `.sysml` file, `views/`, and `layout.json`, are outside
`projects/`. The library refuses to write, delete, or `git add` them.
When the root contains `.sysml` files they stay openable as a read-only
"Repository model" so the old model is still reachable.

The insulin-pump example is not stored in the model repo. It is package
data inside `system-explorer`. Opening it does not copy anything until
someone edits; the edit is then a new folder under `projects/`.

## Consequences

- A restart on Render loses the clone and keeps every project that was
  pushed. A project that was created but not yet committed can be lost if
  the push fails. Creation commits immediately, before the page is sent.
- The model repo gains a `projects/` tree over time. Nothing in this
  change prunes it.
- `system-explorer <folder>` on a folder that already has `.sysml` files
  still opens that folder directly. `--workspace`, hosted mode, and a
  folder with no `.sysml` files use the layout above.
- Collaborators who can sign in can open every project. That matches
  today's single shared model. Per-user directories were rejected because
  they would hide work from the rest of a small team and would still have
  to be committed to the same repo.

## Alternatives considered

- **Keep using the repo root as the one model.** This is the current
  behavior. A new login cannot start clean without wiping the spine-cooling
  files.
- **A Render Disk or Postgres.** Both are extra services. The free Postgres
  expires, and a disk is limited to one instance. Git is already the
  source of truth for the model.
- **One branch or one repo per project.** That needs permissions the
  server's single contents token does not have to create, and it makes
  "open recent" a GitHub API product instead of a directory listing.
- **A per-user path (`projects/<login>/...`) only.** It isolates people,
  which this team does not need, and a shared example copy would have no
  obvious owner. The cookie already separates "what I am looking at".
