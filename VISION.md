# VISION.md

The original idea behind this project and the reasons for it, kept so that anyone
working on it (people or agents) builds what was intended and not just what is in the
code. `AGENTS.md` covers *how* things work; this file covers *what* and *why*.

When a choice isn't covered here or in `AGENTS.md`, ask the owner. Don't guess and
build.

## The idea

A personal tool to keep track of **todos and notes, all tied to projects**. It should
be:

- **Extremely simple.** Structure lives in **filenames**; contents are **almost pure
  markdown**, for simplicity and readability. Each project has a short code and two
  files: `<code>.todos.md` and `<code>.notes.md`.
- **One plain folder** in the user's home (`~/pa` for now; the name is a working
  title, and the GitHub repo is called `pp`).

## What matters most: intake

Getting todos and notes *in* has to be effortless. Three ways in:

1. **Quick-capture modals** bound to a system hotkey: one for todos, one for notes.
   They should appear **instantly**, or stay running hidden until called.
2. **MCP access**, so AI agents can read and change todos and notes.
3. **Full windows** for viewing and working with todos and notes. This part is the
   least settled. For now: navigate with **vim keys**, edit in **`$EDITOR`**,
   nothing fancy. A TUI is expected to be fast enough.

## Todos

- **Pure markdown.** The file holds nothing but checklist items, nested as deep as
  needed. In practice nesting won't go past about 3 levels.

  ```markdown
  - [ ] todo 1
  - [ ] todo with subtasks
    - [ ] subtask 1
  ```

- **Daily rollover.** Unfinished todos carry over each day, so finished work from
  earlier days is **cleared away and each day starts clean**.
  Rollover also gives **a little history without dealing with version control**.
- Old daily files would clutter the folder, so they move into a `history/` folder.
- The date must not come from file metadata: other programs touching the files
  would make it wrong. The date is in the filename instead
  (`<code>.todos.YYYYMMDD.md`).

## Notes

The owner was less sure here and open to suggestions. The starting idea was to keep
all of a project's notes together in **one markdown file**.

## Architecture

- **Client/server.** The server handles all file IO and provides the MCP interface.
- **Clients:**
  - Two modals (todo, note) that appear instantly.
  - Separate **todos** and **notes** windows, each its own client connected to the
    server, so you can **open as many as you want**, e.g. one per project.

## Constraints that came up while refining the idea

- **It must run on Windows too.** That machine has an **aggressive antivirus that
  scans on every file read**: not blocking, just slow and annoying. So read as few
  files as possible and keep dependencies few.
- Because of that, **modals are a separate, swappable piece** that only sends
  messages to the server, so each platform can use whatever modal works best.
- **Python** for now, "good enough", since a rewrite later is acceptable.
- **Monorepo:** git at the root, each piece in its own folder (`server/` first).

## How the owner wants to work

- **Keep it lean.** "Before you go too crazy" means building in small steps and
  checking in.
- **Don't build things that weren't asked for.** A drop-folder way of adding todos
  was suggested, built, and then removed: "a good idea, but not what I needed right
  now". Suggest extras and wait for a yes.
- Work out the design first, then build.

## Decisions made together while refining the idea

These came out of discussion, not the original idea, but are agreed:

- The active todo file carries **the date it is for** in its name; rolled-over files
  keep that date in `history/` (so a project untouched for 5 weeks gets a history
  file dated 5 weeks ago).
- Rollover rule: keep an item if it or anything under it is unfinished; drop
  completely finished branches.
- Notes are one **append-only log per project** with a timestamped heading per entry.
- An `inbox` project exists for captures with no project.
- The server talks **HTTP on localhost** with a token, so any tool can be a client.

## Still open

- Final name (`pa` / `pp` / something else).
- What the windows (TUI/GUI) look like beyond "vim keys + `$EDITOR`".
- How the modals are built on each OS (and how the hotkey works; deliberately out of
  scope so far).
- Whether to add a Unix socket alongside HTTP.
