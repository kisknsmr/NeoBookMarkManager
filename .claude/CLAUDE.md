# Project instructions

## rust-skills

The `actionbook/rust-skills` pack lives in [.agents/skills/](../.agents/skills/) (pinned in
[skills-lock.json](../skills-lock.json)). `.claude/skills` is a **directory junction** to it, which is
what makes the skills discoverable as `/rust-refactor-helper`, `/rust-router`, etc. Do not replace
that junction with a copy — edit the pack in `.agents/skills/` and the lock file stays meaningful.

## The `LSP` tool those skills reference

Several rust-skills declare `allowed-tools: ["LSP", ...]` and show calls like
`LSP(operation: "findReferences", filePath: ..., line: ..., character: ...)`. There is no built-in
`LSP` tool. This project supplies the equivalent through the `rust-lsp` MCP server
([.claude/lsp/rust-lsp-mcp.js](lsp/rust-lsp-mcp.js), registered in [.mcp.json](../.mcp.json)), which
drives a real `rust-analyzer` over LSP. Translate as follows:

| Skill writes | Call instead |
|---|---|
| `LSP(findReferences)` | `mcp__rust-lsp__rust_references` |
| `LSP(hover)` | `mcp__rust-lsp__rust_hover` |
| `LSP(goToDefinition)` / `typeDefinition` / `implementation` | `mcp__rust-lsp__rust_definition` (`kind:`) |
| `LSP(incomingCalls)` / `LSP(outgoingCalls)` | `mcp__rust-lsp__rust_call_hierarchy` (`direction:`) |
| `LSP(documentSymbol)` | `mcp__rust-lsp__rust_document_symbols` |
| `LSP(workspaceSymbol)` | `mcp__rust-lsp__rust_find_symbol` |
| `LSP(rename)` — and any `--dry-run` rename | `mcp__rust-lsp__rust_rename_preview` |
| `LSP(diagnostics)` | `mcp__rust-lsp__rust_diagnostics` |

Conventions that differ from raw LSP:

- **`line` is 1-based** (matches Grep output and editor gutters). `character` stays 0-based and can
  be omitted — it is inferred from the line.
- Most tools accept a bare `symbol` name instead of coordinates. An ambiguous name returns the
  candidate list and refuses to guess; pass `file` + `line`, or `allow_ambiguous: true`.
- `rust_rename_preview` **never writes**. It returns rust-analyzer's exact `WorkspaceEdit`, so the
  `--dry-run` step in rust-refactor-helper is real. Apply the edits with Edit afterwards.
- The first call spawns rust-analyzer and blocks on `cargo metadata` plus cache priming
  (~1-2 min cold on this workspace). Later calls in the same session are fast.
- `rust_diagnostics` triggers `cargo check` through rust-analyzer and waits for it, so it is the
  post-refactor verification step. `cargo check` / `cargo clippy` in Bash remain fine too.

Debug the bridge with `RUST_LSP_DEBUG=1`; it logs LSP traffic to stderr.
