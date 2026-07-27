# MCP

Use this reference when designing or reviewing Cursor MCP artifacts.

## Native paths

- Project MCP config: `.cursor/mcp.json`
- User MCP config: `~/.cursor/mcp.json`
- Plugin MCP config: `<plugin>/mcp.json`

## Native JSON shape

Cursor MCP configuration uses a top-level `mcpServers` object. A server entry
may use a local command with `command`, `args`, and `env`, or a remote server
with `url` and `headers`.

Keep secrets out of files. Prefer environment injection through an explicit
future lifecycle rather than committing secret values or shell-expanded tokens.

## Public module boundary

The current managed builder projection does not install MCP servers, approve
MCPs, or start MCP processes; the machine-readable projection contract is owned
by `config/nddev-contract.json` and `build/manifest.json`. MCP work must remain
a deterministic plan, checker, or design artifact unless a later setup
explicitly owns:

- `mcp.json` location
- server transport and command provenance
- argv and environment boundaries
- authentication boundary
- startup and failure behavior
- removal behavior
- non-live validation

`launch` must continue blocking managed MCP approval overrides unless the public
contract changes in code.
