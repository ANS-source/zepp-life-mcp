# Zepp Life MCP

MCP server for Zepp Life data.

This project provides local caching, sync, and MCP tools for Zepp Life data from either exported files or the Zepp cloud session flow.

## Supported sources

- `export_file` for local Zepp exports
- `cloud_session` for `apptoken`-based cloud access

## Current data coverage

The current implementation targets these data types:

- steps and daily activity
- sleep
- heart rate
- workouts
- body measurements

Cloud coverage can vary by account, region, and upstream endpoint stability. Export mode is the safest option when you need predictable full-history access.

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
```

## Setup

### Cloud session

You need an `apptoken`.

Typical flow:

1. Open `https://user.huami.com/privacy2/index.html`
2. Sign in to the Zepp Life account
3. Open browser DevTools
4. Find the `apptoken` cookie

Then configure the server:

```bash
zepp-life-mcp setup --mode cloud_session --token "<apptoken>" --user-id "<userId>" --region eu
zepp-life-mcp doctor
```

### Export file mode

```bash
zepp-life-mcp setup --mode export_file --export-path ~/Downloads/ZeppExport
zepp-life-mcp doctor
```

## Use

```bash
zepp-life-mcp sync --start-date 2022-01-01 --end-date 2022-12-31
zepp-life-mcp serve
```

## MCP client config

Example `Claude Desktop` config:

```json
{
  "mcpServers": {
    "zepp-life": {
      "command": "zepp-life-mcp",
      "args": ["serve"]
    }
  }
}
```

## Example prompts

- `Show my workouts from the last 30 days`
- `How has my weight changed this year?`
- `Summarize my sleep for the past week`
- `Sync my latest Zepp Life data`

## Commands

```bash
zepp-life-mcp --help
zepp-life-mcp setup --help
zepp-life-mcp doctor
zepp-life-mcp sync --help
zepp-life-mcp serve
```

## Development

```bash
pytest
python -m build
```

## Troubleshooting

- `Connection: failed`
  - verify `apptoken`
  - verify `user_id`
- `No export data found`
  - verify the extracted archive path
  - verify that CSV or JSON export files are present
- `sync` returns no data
  - try another date range
  - try export mode if cloud coverage is incomplete

## Security

- `apptoken` is stored via the system keyring
- do not commit `.env`, exported health data, or local SQLite files
- prefer interactive setup over pasting secrets into shell history

## Disclaimer

This is an unofficial project and is not affiliated with Xiaomi or Zepp Health.
