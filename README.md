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

A small server owns the files and exposes them over a local HTTP API, so quick-capture
popups, terminal UIs and AI agents (via MCP, planned) can all work on the same data.

## Status

Early work in progress. Done: the server (`server/`). Planned: MCP access, terminal
UIs for todos and notes, quick-capture popups.

## Running the server

Requires Python 3.11+, no other dependencies.

```sh
cd server
PYTHONPATH=src python3 -m pa_server.cli serve        # listens on 127.0.0.1:47100
```

Add a todo from anywhere (the token is in `~/pa/.token`):

```sh
curl -H "Authorization: Bearer $(cat ~/pa/.token)" -H 'Content-Type: text/plain' \
     --data-raw '@work todo: call the plumber' localhost:47100/capture
```

Run the tests:

```sh
cd server && PYTHONPATH=src python3 -m unittest discover -s tests
```

See [AGENTS.md](AGENTS.md) for the design and API details.

## License

MIT
