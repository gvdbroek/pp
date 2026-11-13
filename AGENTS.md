# AGENTS.md

`pa` (working title) tracks todos and notes per project, stored as plain markdown in a
user folder. A server owns all file IO and exposes it to clients (TUIs, quick-capture
modals) and to agents (MCP).

**Read [VISION.md](VISION.md) first.** It holds the original idea, the owner's reasons,
and how they want to work. This file covers the implementation.

## Ground rules

- **Keep it lean.** Build what has been agreed; propose extras and wait for a yes.
- **Must run on Linux and Windows.** The Windows machine has an aggressive antivirus
  that scans every file read, so minimise files touched: standard library first,
  few dependencies, small import graphs, no needless re-reads.
- **The markdown files are the source of truth.** No database, no hidden IDs, no
  metadata in files. A human editing in `$EDITOR` must never lose data.

## Repo layout

Monorepo: git at the root, one sub-project per folder.

```
server/                 Python package `pa_server` (stdlib only), command `pa-server`
  src/pa_server/
    todos.py            checklist model: parse/dump, path addressing, mutations, rollover pruning
    notes.py            note log parse/format
    store.py            filesystem layout, lazy rollover, atomic writes, project discovery
    capture.py          plain-text quick-capture format
    service.py          all operations; HTTP (and later MCP) are thin adapters over it
    events.py           event bus + stat-polling watcher (change events, midnight rollover)
    httpapi.py          JSON-over-HTTP API + server-sent events, token auth
    cli.py              `pa-server serve`, `pa-server token`
  tests/                unittest (no pytest dependency)
clients/
  tui/                  Python package `pa_tui` (stdlib curses; `windows-curses` on Windows)
    src/pa_tui/
      api.py            HTTP client: discovery via .server/.token, requests, SSE listener
      ui.py             curses helpers: clipped drawing, line prompt, list picker, $EDITOR
      app.py            shared view loop: vim key sequences, live reload, status line
      todos.py          `pa-todos [project]`
      notes.py          `pa-notes [project]`
    tests/              unit tests + integration tests against a real server
                        (imports ../../server/src)
```

Planned (not started): `clients/` modals. For now the README shows how to build a
modal yourself with a small script that posts to `/capture`.

## Data layout

Root folder: `~/pa`, overridable with `PA_HOME`.

```
~/pa/
  <code>.todos.<YYYYMMDD>.md     active todo list; the date is the day it is for
  <code>.notes.md                note log
  history/<code>.todos.<YYYYMMDD>.md   rolled-over snapshots
  .token                         API token (created once, kept across restarts)
  .server                        {"url", "pid"} while the server runs
```

- Project codes: lowercase `[a-z0-9][a-z0-9_-]*` (no dots: the dot is the filename
  separator). A project exists if its files exist; there is no registry.
- `inbox` is a reserved project that always exists, for captures without a project.

### Todos

- Files contain only markdown checklist items (`- [ ] text`), nested by indentation,
  realistically ≤ 3 levels. Indentation is normalised to 2 spaces on write.
- Non-checklist lines are tolerated: kept as `extra` lines on the item above, or as a
  preamble before the first item. Blank lines are dropped.
- Items are addressed by 1-based dotted paths (`2.1` = first child of second item).
  Mutations accept an `expect` text; if the item at the path has different text the
  call fails (`StaleError`, HTTP 409). This replaces hidden IDs.

### Rollover

Daily, so each day starts clean while keeping history without version control.

- Lazy: runs when a project's todos are first accessed on a new day, and at midnight
  via the watcher. If the active file is dated before today, it moves to `history/` as
  a full snapshot and a new file for today is written with the carried-over items.
- Rule: keep an item if it **or any descendant** is open; drop fully-checked subtrees.
  A checked parent survives if it still has an open child.
- The date comes from the **filename only**, never file mtimes, so outside tools
  (editors, sync) can't confuse it. A project untouched for 5 weeks rolls over to a
  history file dated 5 weeks ago.
- Edge cases: several stale active files are merged (newest first); empty stale files
  are deleted rather than archived; history name clashes get a `.1`, `.2` suffix.

### Notes

One append-only log per project, one entry per `## YYYY-MM-DD HH:MM[ - title]` heading
(`—` also accepted as separator). Parsed entries carry their heading line number so
clients can open `$EDITOR +<line>`.

## Server

- **Writes** are read-modify-write under one process lock, written via temp file +
  `os.replace`, retried briefly on `PermissionError` (Windows: editor/AV holding the file).
- **Change detection** polls `stat()` of the root folder (no reads → no AV scans) and
  publishes `{"type": "changed", "project", "kind": "todos"|"notes"}`. It sees the
  server's own writes and outside edits alike, so it is the single source of events.
- **Transport:** HTTP on loopback (default port 47100, `PA_PORT`), chosen because every
  tool (curl, PowerShell, AutoHotkey, launchers) can speak it, which keeps modal
  clients swappable. Same JSON protocol could later be served on a Unix socket too
  (deferred). Not stdio: the server is long-running and shared by many clients.
- **Auth:** every route except `GET /health` needs `Authorization: Bearer <token>`.
  Required because local web pages can reach localhost.
- **API:** routes are documented at the top of `httpapi.py`. Todo mutations return
  `{"path", "todos"}` (the full updated list) so clients can re-render without a second
  request. `GET /events` is an SSE stream. Errors are `{"error"}` with 400 / 401 / 404 /
  405 / 409.

### Capture format (`POST /capture`)

So a modal can be a single HTTP request. Body is `{"text", "kind"?, "project"?}` or a
`text/plain` body.

```
[@code] [todo:|note:|t:|n:] first line
more lines...
```

- No keyword: one line → todo, several lines → note. Inline `@code`/keyword override
  the `kind`/`project` fields.
- Todo: each non-empty line is a todo, indented lines become subtasks, leading `- ` /
  `- [ ] ` bullets are ignored.
- Note: first line is the title, the rest the body; with no body, the line is the body.
- Unknown project → goes to `inbox` with `@code` kept in the text.
- curl gotcha: use `--data-raw`; `-d`/`--data-binary` treat a leading `@` as a filename.

## Decisions log

| Decision | Why |
|---|---|
| Python, stdlib-first | Windows AV makes native binaries painful (Go false positives); Python runs from a trusted interpreter. Startup cost paid once by the long-running server. Rewrite later is acceptable. |
| Date in active todo filename | Filename is authoritative; mtimes are unreliable with outside edits. |
| Path + `expect` addressing | Keeps files pure markdown while making concurrent edits safe. |
| Single notes log per project | Append-only is trivial and conflict-free; split later only if needed. |
| HTTP on loopback + token | Universally scriptable; SSE gives push updates; MCP's network transport is HTTP. |
| Modals are separate, swappable clients | Windows AV may force different modal implementations per OS. |
| curses for the TUIs | Few files to scan at startup; the views are simple. |
| Drop-folder capture | Built, then removed: not needed now. Don't re-add unasked. |

## TUI clients

- **curses, not Textual:** chosen to stay lean. Textual would read hundreds of files at
  every start under the Windows AV; the views are just lists with vim keys plus
  `$EDITOR`, which curses handles fine.
- Each window is its own process and HTTP client; open as many as you like. Each
  listens to `/events` and reloads when its project/kind changes (also after
  reconnecting, since events may have been missed).
- Every mutation sends `expect` (the item text it acted on). On 409 the view reloads and
  shows the error, so a stale screen can't edit the wrong item.
- Editing text in depth is delegated to `$EDITOR` (`$VISUAL` first; `+line` for vi-like
  editors, `file:line` for helix). After the editor exits the view reloads.
- Key sequences (`gg`, `dd`, `>>`, `<<`, `cw`) are buffered in `App.on_key`.
- New notes from `a` follow the capture rule: with several lines, the first is the title.

## Development

```sh
cd server
PYTHONPATH=src python3 -m unittest discover -s tests     # run tests
PYTHONPATH=src python3 -m pa_server.cli serve            # run the server (~/pa)
PYTHONPATH=src python3 -m pa_server.cli --root /tmp/x serve --port 47199

cd clients/tui
PYTHONPATH=src python3 -m unittest discover -s tests
PYTHONPATH=src python3 -m pa_tui.todos [project]         # needs a running server

pip install ./server ./clients/tui                       # installs pa-server, pa-todos, pa-notes
```

Requires Python ≥ 3.11. No third-party dependencies except `windows-curses` on Windows.

## Status / next

- Done: core model, store + rollover, HTTP API, events, capture; TUI views for todos
  and notes.
- Next (proposed, not yet confirmed): `pa-server mcp`, a stdio MCP adapter for agents that forwards to the
  running server. Plan is to hand-write the small MCP subset needed (initialize,
  tools/list, tools/call) rather than use the SDK, to keep agent-spawned startup cheap
  under AV.
- Later: modal clients, optional Unix socket listener, autostart/restart, creating
  projects from the TUI.
- Undecided: final project name.
