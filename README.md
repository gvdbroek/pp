# pa

Plain-markdown todos and notes, organised per project.

Everything lives in one folder (`~/pa` by default) as ordinary markdown files you can
read and edit by hand:

```
~/pa/
  work.todos.20261113.md    today's todos for project "work"
  work.notes.md             notes for "work"
  history/                  previous days' todo lists
```

Unfinished todos roll over to a fresh file each day; the old file moves to `history/`.

A small server owns the files and exposes them over a local HTTP API, so terminal UIs,
quick-capture popups and AI agents (via MCP, planned) can all work on the same data.

## Status

Early work in progress. Done: the server (`server/`) and terminal views for todos and
notes (`clients/tui/`). Planned: MCP access, ready-made quick-capture modals.

## Getting started

Requires Python 3.11+. No other dependencies (on Windows, `windows-curses` is installed
automatically for the terminal views).

### 1. Install

```sh
pip install ./server ./clients/tui      # or: pipx install ./server, pipx install ./clients/tui
```

This gives you three commands: `pa-server`, `pa-todos` and `pa-notes`.

### 2. Start the server

```sh
pa-server serve           # listens on 127.0.0.1:47100, data in ~/pa
```

Keep it running (a terminal tab, or your OS's autostart). Set `PA_HOME` to use another
folder and `PA_PORT` for another port. The clients find the server by themselves
through `~/pa/.server` and `~/pa/.token`.

### 3. Create a project and open the views

```sh
curl -H "Authorization: Bearer $(cat ~/pa/.token)" -d '{"code":"work"}' localhost:47100/projects

pa-todos work             # todo list for "work"
pa-notes work             # notes for "work"
pa-todos                  # no project given: pick one from a list
```

Open as many windows as you like; they all update live when anything changes, including
edits you make to the files by hand.

**Todos:** `j`/`k` move, `gg`/`G` top/bottom, `x` or `space` toggle, `o`/`O` add
below/above, `a` add sub-item, `i` edit, `cw` replace text, `dd` delete, `>>`/`<<`
indent/outdent, `e` open the file in `$EDITOR` at that item, `p` switch project,
`?` show all keys, `q` quit.

**Notes:** `j`/`k` move (newest first, preview below), `Enter`/`e` open the notes file in
`$EDITOR` at that note, `a` write a new note in `$EDITOR` (with more than one line, the
first line becomes the title), `p` switch project, `?` show all keys, `q` quit.

### 4. Make your own quick-capture modal

A modal is anything that sends text to `POST /capture`, so you can build one with any
tool and bind it to a hotkey however your OS does that. The text format:

```
[@project] [todo:|note:] text
```

A single line is a todo, several lines are a note; `@project` defaults to `inbox`.

**Linux / macOS:** a tiny script, bound to a hotkey that opens it in a small floating
terminal (e.g. `foot --app-id pa-capture pa-capture`, then make that window float in
your window manager):

```sh
#!/bin/sh
# pa-capture: type a line, press Enter.  Example input: "@work call the plumber"
printf 'capture> '
read -r line || exit
[ -n "$line" ] || exit
curl -s -H "Authorization: Bearer $(cat ~/pa/.token)" -H 'Content-Type: text/plain' \
     --data-raw "$line" localhost:47100/capture >/dev/null
```

For a notes modal, send `"note: $line"` instead of `"$line"`.

**Windows:** the same in PowerShell, bound to a hotkey with AutoHotkey, PowerToys or a
shortcut key on a `.lnk`:

```powershell
# pa-capture.ps1
$text = Read-Host "capture"
if ($text) {
  $token = (Get-Content "$HOME\pa\.token").Trim()
  Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:47100/capture" `
    -Headers @{ Authorization = "Bearer $token" } -ContentType "text/plain; charset=utf-8" `
    -Body ([Text.Encoding]::UTF8.GetBytes($text)) | Out-Null
}
```

With curl, always use `--data-raw`: `-d` treats text starting with `@` as a filename.

## Development

```sh
cd server      && PYTHONPATH=src python3 -m unittest discover -s tests
cd clients/tui && PYTHONPATH=src python3 -m unittest discover -s tests
```

See [VISION.md](VISION.md) for the idea behind the project and [AGENTS.md](AGENTS.md)
for the design and API details.

## License

MIT
