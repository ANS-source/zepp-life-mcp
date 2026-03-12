# Zepp Life MCP

Отдельный MCP-сервер для `Zepp Life`.

Поддерживает:

- `export_file`
- `cloud_session`

Данные:

- шаги
- сон
- пульс
- тренировки
- вес и состав тела

## Установка

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e "."
```

## Команды

```bash
zepp-life-mcp setup
zepp-life-mcp doctor
zepp-life-mcp sync --start-date 2022-01-01 --end-date 2022-12-31
zepp-life-mcp serve
```

## Настройка Claude Desktop

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
