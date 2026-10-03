# Oracle PL/SQL Analysis MCP

Python, read-only Oracle Database MCP server.

## Start in a new environment

Prerequisites: Python 3.12 or newer, network access to the Oracle database,
and an Oracle account restricted to read-only access.

Clone or copy the project, then create an isolated Python environment and
install the application:

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
cp .env.example .env
```

Edit `.env` to choose the target Oracle database. For a direct connection:

```env
ORACLE_USER=readonly_user
ORACLE_PASSWORD=replace-with-a-secret
ORACLE_CONNECT_STRING=db.example.com:1521/SERVICE_NAME
ORACLE_DEFAULT_SCHEMA=APP_SCHEMA
ORACLE_CONFIG_DIR=
ORACLE_WALLET_LOCATION=
```

For Oracle Autonomous Database or another wallet-backed connection, point the
configuration values at the directory that contains `tnsnames.ora` and use its
alias:

```env
ORACLE_USER=readonly_user
ORACLE_PASSWORD=replace-with-a-secret
ORACLE_CONNECT_STRING=my_database_low
ORACLE_CONFIG_DIR=/absolute/path/to/oracle-wallet
ORACLE_WALLET_LOCATION=/absolute/path/to/oracle-wallet
ORACLE_DEFAULT_SCHEMA=APP_SCHEMA
```

Do not commit `.env`; it contains credentials.

### Local MCP client (stdio)

The default transport is `stdio`. Start it with:

```bash
oracle-plsql-mcp
```

For example, an MCP client can configure it as:

```json
{
  "mcpServers": {
    "oracle-plsql": {
      "command": "/absolute/path/oracle-plsql-mcp/.venv/bin/oracle-plsql-mcp"
    }
  }
}
```

### HTTP

To run the MCP server over HTTP, set the transport in `.env` (or in the
process environment) and start the same command:

```env
MCP_TRANSPORT=streamable-http
```

```bash
oracle-plsql-mcp
```

The server uses FastMCP's `streamable-http` transport. Check the startup log
for the bound HTTP address before configuring an HTTP MCP client.

The server has no DML, DDL, or arbitrary-SQL tool. It should use a dedicated
database account with genuinely read-only privileges. `explain_sql_query` may
write temporary rows to Oracle's `PLAN_TABLE`, which are removed in the same
session.

## Docker

The included `Dockerfile` runs the server as an HTTP MCP service on port 8000.
Build the image from the project root:

```bash
docker build -t oracle-plsql-mcp:local .
```

Create a runtime configuration from the sample and fill in the Oracle
credentials and connection details. Do not put a real `.env` file or an Oracle
wallet in the image.

```bash
cp .env.example .env
# Edit .env with the Oracle connection settings.
```

For a direct Oracle connection, start the container with:

```bash
docker run --rm --name oracle-plsql-mcp \
  --env-file .env \
  -e MCP_TRANSPORT=streamable-http \
  -e MCP_HOST=0.0.0.0 \
  -e MCP_PORT=8000 \
  -p 8000:8000 \
  oracle-plsql-mcp:local
```

For a wallet-backed connection, mount the wallet read-only and use the
_container_ path in `.env`:

```env
ORACLE_CONNECT_STRING=my_database_low
ORACLE_CONFIG_DIR=/run/secrets/oracle-wallet
ORACLE_WALLET_LOCATION=/run/secrets/oracle-wallet
```

```bash
docker run --rm --name oracle-plsql-mcp \
  --env-file .env \
  -e MCP_TRANSPORT=streamable-http \
  -e MCP_HOST=0.0.0.0 \
  -p 8000:8000 \
  -v "$PWD/oracle-wallet:/run/secrets/oracle-wallet:ro" \
  oracle-plsql-mcp:local
```

The Streamable HTTP MCP endpoint is `http://localhost:8000/mcp`.

### Test the container and MCP server

With the container running, confirm that it started:

```bash
docker logs oracle-plsql-mcp
```

Then initialize an MCP session. A response containing server information
confirms that the HTTP MCP endpoint is reachable; it does not need an Oracle
connection. The commands store the session ID for the following requests.

```bash
MCP_HEADERS="$(mktemp)"
curl --silent --show-error --dump-header "$MCP_HEADERS" --output /dev/null \
  --request POST http://localhost:8000/mcp \
  --header 'Content-Type: application/json' \
  --header 'Accept: application/json, text/event-stream' \
  --data '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"curl-check","version":"1.0"}}}'
MCP_SESSION_ID="$(tr -d '\r' < "$MCP_HEADERS" | awk 'tolower($1) == "mcp-session-id:" {print $2}')"
rm "$MCP_HEADERS"
test -n "$MCP_SESSION_ID" && echo "MCP session: $MCP_SESSION_ID"
```

List the registered tools to verify the MCP protocol exchange. The response is
an SSE `event: message` containing JSON-RPC data and includes `ping_oracle`.

```bash
curl --silent --show-error --request POST http://localhost:8000/mcp \
  --header 'Content-Type: application/json' \
  --header 'Accept: application/json, text/event-stream' \
  --header "Mcp-Session-Id: $MCP_SESSION_ID" \
  --data '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}'
```

Finally invoke `ping_oracle` to verify that the configured Oracle database is
reachable. A successful result contains:

```json
{ "ok": true }
```

```bash
curl --silent --show-error --request POST http://localhost:8000/mcp \
  --header 'Content-Type: application/json' \
  --header 'Accept: application/json, text/event-stream' \
  --header "Mcp-Session-Id: $MCP_SESSION_ID" \
  --data '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"ping_oracle","arguments":{}}}'
```

For a containerized stdio MCP client, replace the image command with a `docker
run -i --rm --env-file /path/to/.env oracle-plsql-mcp:local` command. Do not
publish a port in that mode.

## Tools

Metadata: `ping_oracle`, `explain_sql_query`, `list_tables`, `describe_table`,
`get_table_structure_details`, `get_object_privileges`,
`get_table_relationships`, `get_object_grants_and_synonyms`,
`get_table_automation`, `get_partition_details`,
`get_view_definition_and_dependencies`, `get_table_statistics`,
`get_index_usage`, `find_unused_or_stale_objects`, `get_session_context`,
`get_trigger_source_and_dependencies`, `search_objects`,
`get_object_source`, `search_source`, `find_object_dependencies`,
`find_object_dependents`, `get_object_ddl`, `get_invalid_objects`,
`check_syntax_errors`, `get_scheduler_jobs`, `get_sql_plan_baseline_info`,
`get_package_hierarchy`, `get_routine_signature`.

PL/SQL analysis: `find_plsql_symbol`, `find_plsql_references`,
`find_plsql_callers`, `find_plsql_callees`, `get_plsql_call_graph`,
`get_routine_data_access`, `find_dynamic_sql`, `find_column_usage`,
`analyze_db_change_impact`.

All PL/SQL results retain source-line evidence. Call and data-access discovery
only claims statically visible syntax; `EXECUTE IMMEDIATE` and `OPEN ... FOR`
are reported as explicit uncertainty evidence rather than guessed dependencies.
`explain_sql_query` accepts only a single, non-locking `SELECT` or `WITH`
statement and requires an accessible Oracle `PLAN_TABLE`.

Several Oracle dictionary views are privilege-sensitive. In particular,
`get_sql_plan_baseline_info` intentionally uses `USER_SQL_PLAN_BASELINES`,
because Oracle does not provide an `ALL_SQL_PLAN_BASELINES` view. The column
usage tool returns static lexical evidence rather than claiming complete
column-level dependency resolution; aliases and dynamic SQL must be reviewed.
`get_index_usage` reports index health and optimizer statistics; the standard
`ALL_*` views cannot reliably establish historical runtime usage.
