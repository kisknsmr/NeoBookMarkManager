#!/usr/bin/env node
/**
 * rust-lsp-mcp - a zero-dependency MCP server that bridges Claude Code to
 * rust-analyzer over LSP, so the `.agents/skills` rust-skills (which assume an
 * `LSP` tool) have real symbol/reference/call-hierarchy data to work with.
 *
 * MCP transport : newline-delimited JSON-RPC on stdio (stdout is MCP-only).
 * LSP transport : Content-Length framed JSON-RPC to a spawned rust-analyzer.
 * Diagnostics   : stderr.
 */

'use strict';

const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');

const PROJECT_ROOT = process.env.RUST_LSP_ROOT || process.cwd();
const RA_BIN = process.env.RUST_ANALYZER_BIN || 'rust-analyzer';
const INDEX_TIMEOUT_MS = Number(process.env.RUST_LSP_INDEX_TIMEOUT_MS || 180000);
const REQUEST_TIMEOUT_MS = Number(process.env.RUST_LSP_REQUEST_TIMEOUT_MS || 60000);

const DEBUG = !!process.env.RUST_LSP_DEBUG;

const log = (...a) => process.stderr.write('[rust-lsp-mcp] ' + a.join(' ') + '\n');

/* ------------------------------------------------------------------ paths */

function toUri(p) {
  let abs = path.resolve(PROJECT_ROOT, p).replace(/\\/g, '/');
  if (!abs.startsWith('/')) abs = '/' + abs;           // C:/x -> /C:/x
  return 'file://' + encodeURI(abs).replace(/#/g, '%23').replace(/\?/g, '%3F');
}

function fromUri(uri) {
  if (!uri || !uri.startsWith('file://')) return uri;
  let p = decodeURIComponent(uri.slice('file://'.length));
  if (/^\/[A-Za-z]:/.test(p)) p = p.slice(1);          // /C:/x -> C:/x
  const rel = path.relative(PROJECT_ROOT, p).replace(/\\/g, '/');
  return rel && !rel.startsWith('..') ? rel : p;
}

/* -------------------------------------------------------------- LSP client */

class RustAnalyzer {
  constructor() {
    this.proc = null;
    this.nextId = 1;
    this.pending = new Map();
    this.buf = Buffer.alloc(0);
    this.opened = new Set();
    this.diagnostics = new Map();      // uri -> Diagnostic[]
    this.ready = null;
    this.indexed = false;
  }

  start() {
    if (!this.ready) this.ready = this._start();
    return this.ready;
  }

  async _start() {
    log('spawning', RA_BIN, 'in', PROJECT_ROOT);
    this.proc = spawn(RA_BIN, [], {
      cwd: PROJECT_ROOT,
      stdio: ['pipe', 'pipe', 'pipe'],
      shell: process.platform === 'win32',   // resolve the rustup .exe shim
    });
    this.proc.on('error', (e) => log('spawn failed:', e.message));
    this.proc.stderr.on('data', (d) => {
      const s = d.toString().trim();
      if (s) log('ra:', s.split('\n').slice(-1)[0].slice(0, 200));
    });
    this.proc.stdout.on('data', (d) => this._onData(d));
    this.proc.on('exit', (code) => {
      log('rust-analyzer exited', code);
      for (const { reject, timer } of this.pending.values()) {
        clearTimeout(timer);
        reject(new Error('rust-analyzer exited'));
      }
      this.pending.clear();
      this.ready = null;
      this.proc = null;
      this.opened.clear();
      this.indexed = false;
    });

    await this.request('initialize', {
      processId: process.pid,
      rootUri: toUri('.'),
      workspaceFolders: [{ uri: toUri('.'), name: path.basename(PROJECT_ROOT) }],
      capabilities: {
        general: { positionEncodings: ['utf-16'] },
        workspace: {
          workspaceFolders: true,
          symbol: { symbolKind: { valueSet: Array.from({ length: 26 }, (_, i) => i + 1) } },
          workspaceEdit: { documentChanges: true, resourceOperations: ['create', 'rename', 'delete'] },
          configuration: true,
        },
        textDocument: {
          synchronization: { didSave: true, dynamicRegistration: false },
          hover: { contentFormat: ['markdown', 'plaintext'] },
          definition: { linkSupport: true },
          typeDefinition: { linkSupport: true },
          implementation: { linkSupport: true },
          references: {},
          documentSymbol: { hierarchicalDocumentSymbolSupport: true },
          callHierarchy: { dynamicRegistration: false },
          rename: { prepareSupport: true },
          publishDiagnostics: { relatedInformation: true },
        },
        window: { workDoneProgress: true },
      },
      initializationOptions: {
        cargo: { buildScripts: { enable: true } },
        procMacro: { enable: true },
      },
    });
    this.notify('initialized', {});
    log('initialized, waiting for indexing');
    await this._waitForIndex();
    log('index ready');
  }

  _waitForIndex() {
    if (this.indexed) return Promise.resolve();
    return new Promise((resolve) => {
      const done = () => { this.indexed = true; clearTimeout(t); resolve(); };
      this._indexDone = done;
      const t = setTimeout(() => {
        log('index wait timed out; proceeding with partial data');
        done();
      }, INDEX_TIMEOUT_MS);
    });
  }

  /* -- framing -- */

  _onData(chunk) {
    this.buf = Buffer.concat([this.buf, chunk]);
    for (;;) {
      const sep = this.buf.indexOf('\r\n\r\n');
      if (sep < 0) return;
      const header = this.buf.slice(0, sep).toString('ascii');
      const m = /content-length:\s*(\d+)/i.exec(header);
      if (!m) { this.buf = this.buf.slice(sep + 4); continue; }
      const len = Number(m[1]);
      const start = sep + 4;
      if (this.buf.length < start + len) return;
      const body = this.buf.slice(start, start + len).toString('utf8');
      this.buf = this.buf.slice(start + len);
      let msg;
      try { msg = JSON.parse(body); } catch (e) { continue; }
      this._dispatch(msg);
    }
  }

  _send(msg) {
    if (!this.proc) throw new Error('rust-analyzer is not running');
    const body = Buffer.from(JSON.stringify(msg), 'utf8');
    this.proc.stdin.write('Content-Length: ' + body.length + '\r\n\r\n');
    this.proc.stdin.write(body);
  }

  _dispatch(msg) {
    // response to one of our requests
    if (msg.id !== undefined && msg.method === undefined && this.pending.has(msg.id)) {
      const { resolve, reject, timer } = this.pending.get(msg.id);
      this.pending.delete(msg.id);
      clearTimeout(timer);
      if (msg.error) reject(new Error(msg.error.message || JSON.stringify(msg.error)));
      else resolve(msg.result);
      return;
    }
    // server -> client request: must answer or rust-analyzer stalls
    if (msg.id !== undefined && msg.method) {
      let result = null;
      if (msg.method === 'workspace/configuration') {
        const items = (msg.params && msg.params.items) || [{}];
        result = items.map(() => ({}));
      }
      this._send({ jsonrpc: '2.0', id: msg.id, result });
      return;
    }
    // notifications
    if (DEBUG) {
      if (msg.method === '$/progress') {
        const v = msg.params.value || {};
        log('progress', String(msg.params.token), v.kind || '', v.message || '');
      } else if (msg.method !== 'textDocument/publishDiagnostics') {
        log('notify', msg.method, JSON.stringify(msg.params || {}).slice(0, 300));
      }
    }
    if (msg.method === 'window/showMessage' && msg.params && msg.params.type <= 2) {
      log('rust-analyzer says:', String(msg.params.message).slice(0, 400));
    }
    if (msg.method === 'textDocument/publishDiagnostics' && msg.params) {
      this.diagnostics.set(msg.params.uri, msg.params.diagnostics || []);
      return;
    }
    if (msg.method === '$/progress' && msg.params) {
      const tok = String(msg.params.token || '');
      const val = msg.params.value || {};
      if (val.kind === 'end' && /indexing|cachePriming/i.test(tok)) {
        if (this._indexDone) { const d = this._indexDone; this._indexDone = null; d(); }
      }
      if (val.kind === 'end' && /flycheck|check/i.test(tok)) {
        if (this._flycheckDone) { const d = this._flycheckDone; this._flycheckDone = null; d(); }
      }
    }
  }

  request(method, params) {
    const id = this.nextId++;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error('LSP request timed out: ' + method));
      }, REQUEST_TIMEOUT_MS);
      this.pending.set(id, { resolve, reject, timer });
      try { this._send({ jsonrpc: '2.0', id, method, params }); }
      catch (e) { this.pending.delete(id); clearTimeout(timer); reject(e); }
    });
  }

  notify(method, params) { this._send({ jsonrpc: '2.0', method, params }); }

  /** Ask rust-analyzer to run `cargo check` now and wait for it to finish.
   *  Without this, diagnostics only appear after a real editor save. */
  runFlycheck(timeoutMs) {
    this.diagnostics.clear();
    return new Promise((resolve) => {
      const done = () => { clearTimeout(t); resolve(); };
      this._flycheckDone = done;
      const t = setTimeout(() => {
        log('flycheck wait timed out');
        this._flycheckDone = null;
        resolve();
      }, timeoutMs);
      try { this.notify('rust-analyzer/runFlycheck', { textDocument: null }); }
      catch (e) { this._flycheckDone = null; clearTimeout(t); resolve(); }
    });
  }

  async open(file) {
    const uri = toUri(file);
    if (this.opened.has(uri)) return uri;
    const abs = path.resolve(PROJECT_ROOT, file);
    if (!fs.existsSync(abs)) throw new Error('file not found: ' + file);
    this.notify('textDocument/didOpen', {
      textDocument: { uri, languageId: 'rust', version: 1, text: fs.readFileSync(abs, 'utf8') },
    });
    this.opened.add(uri);
    await new Promise((r) => setTimeout(r, 200));
    return uri;
  }
}

const ra = new RustAnalyzer();

/* --------------------------------------------------------- symbol helpers */

const KINDS = ['', 'File', 'Module', 'Namespace', 'Package', 'Class', 'Method', 'Property', 'Field',
  'Constructor', 'Enum', 'Interface', 'Function', 'Variable', 'Constant', 'String', 'Number',
  'Boolean', 'Array', 'Object', 'Key', 'Null', 'EnumMember', 'Struct', 'Event', 'Operator', 'TypeParameter'];
const kindName = (k) => KINDS[k] || ('Kind' + k);
const asList = (x) => (x == null ? [] : Array.isArray(x) ? x : [x]);

function rangeOf(loc) {
  return loc.range || loc.targetSelectionRange || loc.targetRange || { start: { line: 0, character: 0 } };
}

function locLabel(loc) {
  if (!loc) return '?';
  return fromUri(loc.uri || loc.targetUri) + ':' + (rangeOf(loc).start.line + 1);
}

function sourceLine(loc) {
  try {
    const abs = path.resolve(PROJECT_ROOT, fromUri(loc.uri || loc.targetUri));
    const l = fs.readFileSync(abs, 'utf8').split(/\r?\n/)[rangeOf(loc).start.line] || '';
    return l.trim().slice(0, 160);
  } catch (e) { return ''; }
}

/** Resolve a target to { uri, position, label }. Accepts explicit file + line
 *  (1-based, like grep and editors) or a bare symbol name. */
async function resolveTarget(args) {
  if (args.file && args.line) {
    const uri = await ra.open(args.file);
    const line = Number(args.line) - 1;
    let character = args.character !== undefined ? Number(args.character) : null;
    if (character === null) {
      // aim at the identifier: prefer `symbol` on that line, else first word char
      const src = fs.readFileSync(path.resolve(PROJECT_ROOT, args.file), 'utf8').split(/\r?\n/)[line] || '';
      const idx = args.symbol ? src.indexOf(args.symbol) : -1;
      character = idx >= 0 ? idx : Math.max(0, src.search(/[A-Za-z_]/));
    }
    return { uri, position: { line, character }, label: args.file + ':' + args.line };
  }
  if (!args.symbol) throw new Error('provide either `symbol`, or `file` plus `line`');

  const hits = asList(await ra.request('workspace/symbol', { query: args.symbol }));
  const exact = hits.filter((h) => h.name === args.symbol);
  const pool = exact.length ? exact : hits;
  if (!pool.length) throw new Error('symbol not found in workspace: ' + args.symbol);
  if (pool.length > 1 && !args.allow_ambiguous) {
    const list = pool.slice(0, 12)
      .map((h) => '  - ' + h.name + ' (' + kindName(h.kind) + ') at ' + locLabel(h.location));
    throw new Error(
      '`' + args.symbol + '` is ambiguous (' + pool.length + ' matches). Re-run with file+line, ' +
      'or allow_ambiguous:true to take the first.\n' + list.join('\n')
    );
  }
  const loc = pool[0].location;
  const file = fromUri(loc.uri);
  const uri = await ra.open(file);
  const pos = rangeOf(loc).start;
  return { uri, position: pos, label: file + ':' + (pos.line + 1) + ' (' + kindName(pool[0].kind) + ')' };
}

/* ------------------------------------------------------------------- tools */

const POS_PROPS = {
  symbol: { type: 'string', description: 'symbol name, resolved via workspace/symbol' },
  file: { type: 'string', description: 'file path relative to project root' },
  line: { type: 'number', description: '1-based line number' },
  character: { type: 'number', description: '0-based column; inferred from the line when omitted' },
  allow_ambiguous: { type: 'boolean', description: 'take the first match instead of erroring' },
};

const TOOLS = {
  rust_find_symbol: {
    description:
      'Search workspace symbols by name (fuzzy), returning kind and file:line for each match. ' +
      'Use this first when you only know a name - it feeds the other tools.',
    schema: {
      type: 'object',
      properties: {
        query: { type: 'string', description: 'symbol name or fragment' },
        limit: { type: 'number', description: 'max results, default 40' },
      },
      required: ['query'],
    },
    async run(a) {
      const hits = asList(await ra.request('workspace/symbol', { query: a.query }));
      if (!hits.length) return 'No workspace symbol matches "' + a.query + '".';
      const lines = hits.slice(0, a.limit || 40).map((h) =>
        locLabel(h.location) + '  ' + kindName(h.kind) + '  ' + h.name +
        (h.containerName ? '  (in ' + h.containerName + ')' : ''));
      return hits.length + ' match(es) for "' + a.query + '":\n' + lines.join('\n');
    },
  },

  rust_references: {
    description:
      'Find ALL references to a symbol using rust-analyzer semantic search, not text search. ' +
      'The pre-flight check for any rename or move refactor. Results are grouped by file.',
    schema: {
      type: 'object',
      properties: Object.assign({
        include_declaration: { type: 'boolean', description: 'default true' },
      }, POS_PROPS),
    },
    async run(a) {
      const t = await resolveTarget(a);
      const refs = asList(await ra.request('textDocument/references', {
        textDocument: { uri: t.uri },
        position: t.position,
        context: { includeDeclaration: a.include_declaration !== false },
      }));
      if (!refs.length) return 'No references found for ' + t.label + '.';
      const byFile = new Map();
      for (const r of refs) {
        const f = fromUri(r.uri);
        if (!byFile.has(f)) byFile.set(f, []);
        byFile.get(f).push(r);
      }
      let out = refs.length + ' reference(s) to ' + t.label + ', across ' + byFile.size + ' file(s):\n';
      for (const [f, list] of [...byFile.entries()].sort()) {
        out += '\n' + f + '  (' + list.length + ')\n';
        list.sort((x, y) => x.range.start.line - y.range.start.line);
        for (const r of list) {
          out += '  ' + String(r.range.start.line + 1).padStart(5) + ': ' + sourceLine(r) + '\n';
        }
      }
      return out;
    },
  },

  rust_hover: {
    description: 'Type signature and doc comment for a symbol - what rust-analyzer actually knows about it.',
    schema: { type: 'object', properties: Object.assign({}, POS_PROPS) },
    async run(a) {
      const t = await resolveTarget(a);
      const h = await ra.request('textDocument/hover', { textDocument: { uri: t.uri }, position: t.position });
      if (!h || !h.contents) return 'No hover info at ' + t.label + '.';
      const c = h.contents;
      const text = typeof c === 'string' ? c
        : Array.isArray(c) ? c.map((x) => (typeof x === 'string' ? x : x.value)).join('\n')
        : c.value;
      return t.label + '\n\n' + text;
    },
  },

  rust_definition: {
    description: 'Go to a definition, type definition, or the implementations of a trait or type.',
    schema: {
      type: 'object',
      properties: Object.assign({
        kind: {
          type: 'string', enum: ['definition', 'type_definition', 'implementation'],
          description: 'default definition',
        },
      }, POS_PROPS),
    },
    async run(a) {
      const t = await resolveTarget(a);
      const method = a.kind === 'type_definition' ? 'textDocument/typeDefinition'
        : a.kind === 'implementation' ? 'textDocument/implementation'
        : 'textDocument/definition';
      const res = asList(await ra.request(method, { textDocument: { uri: t.uri }, position: t.position }));
      if (!res.length) return 'No ' + (a.kind || 'definition') + ' found for ' + t.label + '.';
      return res.map((r) => locLabel(r) + '  ' + sourceLine(r)).join('\n');
    },
  },

  rust_call_hierarchy: {
    description:
      'Who calls this function (incoming) or what it calls (outgoing). Use before moving or ' +
      'inlining a function to see the real call flow.',
    schema: {
      type: 'object',
      properties: Object.assign({
        direction: { type: 'string', enum: ['incoming', 'outgoing'], description: 'default incoming' },
      }, POS_PROPS),
    },
    async run(a) {
      const t = await resolveTarget(a);
      const items = asList(await ra.request('textDocument/prepareCallHierarchy', {
        textDocument: { uri: t.uri }, position: t.position,
      }));
      if (!items.length) return 'No call-hierarchy item at ' + t.label + ' (is it a function?).';
      const outgoing = a.direction === 'outgoing';
      const method = outgoing ? 'callHierarchy/outgoingCalls' : 'callHierarchy/incomingCalls';
      let out = (outgoing ? 'outgoing' : 'incoming') + ' calls for ' + items[0].name + ' (' + t.label + '):\n';
      for (const item of items) {
        const calls = asList(await ra.request(method, { item }));
        if (!calls.length) { out += '  (none)\n'; continue; }
        for (const c of calls) {
          const peer = outgoing ? c.to : c.from;
          const sites = (c.fromRanges || []).map((r) => r.start.line + 1).join(', ');
          out += '  ' + peer.name + '  ' + fromUri(peer.uri) + ':' +
            (peer.selectionRange.start.line + 1) + (sites ? '  [call sites: ' + sites + ']' : '') + '\n';
        }
      }
      return out;
    },
  },

  rust_document_symbols: {
    description:
      'Outline of one file: every item with its line range. Good for sizing up a large module ' +
      'before splitting it.',
    schema: {
      type: 'object',
      properties: { file: { type: 'string', description: 'path relative to project root' } },
      required: ['file'],
    },
    async run(a) {
      const uri = await ra.open(a.file);
      const syms = asList(await ra.request('textDocument/documentSymbol', { textDocument: { uri } }));
      if (!syms.length) return 'No symbols reported for ' + a.file + '.';
      let out = a.file + '\n';
      const walk = (list, depth) => {
        const sorted = list.slice().sort((x, y) =>
          rangeOf(x.location || x).start.line - rangeOf(y.location || y).start.line);
        for (const s of sorted) {
          const r = s.range || (s.location && s.location.range);
          const span = r ? (r.start.line + 1) + '-' + (r.end.line + 1) : '?';
          out += '  '.repeat(depth + 1) + span.padEnd(12) + ' ' + kindName(s.kind).padEnd(10) + ' ' +
            s.name + (s.detail ? '  ' + s.detail : '') + '\n';
          if (s.children && s.children.length) walk(s.children, depth + 1);
        }
      };
      walk(syms, 0);
      return out;
    },
  },

  rust_rename_preview: {
    description:
      'DRY RUN for a rename: asks rust-analyzer for the exact WorkspaceEdit it would apply and ' +
      'reports every file, line and replacement without writing anything.',
    schema: {
      type: 'object',
      properties: Object.assign({
        new_name: { type: 'string', description: 'the proposed new identifier' },
      }, POS_PROPS),
      required: ['new_name'],
    },
    async run(a) {
      const t = await resolveTarget(a);
      const edit = await ra.request('textDocument/rename', {
        textDocument: { uri: t.uri }, position: t.position, newName: a.new_name,
      });
      if (!edit) return 'rust-analyzer declined to rename ' + t.label + ' (not a renameable symbol?).';
      const groups = [];
      if (edit.changes) {
        for (const uri of Object.keys(edit.changes)) groups.push([fromUri(uri), edit.changes[uri]]);
      }
      if (edit.documentChanges) {
        for (const dc of edit.documentChanges) {
          if (dc.textDocument && dc.edits) groups.push([fromUri(dc.textDocument.uri), dc.edits]);
          else groups.push(['(' + dc.kind + ') ' + fromUri(dc.oldUri || dc.uri) +
            (dc.newUri ? ' -> ' + fromUri(dc.newUri) : ''), []]);
        }
      }
      let total = 0;
      let out = 'DRY RUN - rename ' + t.label + ' -> ' + a.new_name + '\n';
      for (const [label, edits] of groups) {
        out += '\n' + label + '  (' + edits.length + ' edit(s))\n';
        edits.sort((x, y) => x.range.start.line - y.range.start.line);
        for (const e of edits) {
          total++;
          out += '  line ' + String(e.range.start.line + 1).padStart(5) +
            ' cols ' + e.range.start.character + '-' + e.range.end.character +
            ' -> ' + JSON.stringify(e.newText) + '\n';
        }
      }
      out += '\n' + total + ' edit(s) across ' + groups.length + ' location group(s). Nothing was written.';
      return out;
    },
  },

  rust_diagnostics: {
    description:
      'Run `cargo check` through rust-analyzer and report the diagnostics. Call after applying a ' +
      'refactor to confirm the tree still compiles. Omit `file` to see the whole workspace.',
    schema: {
      type: 'object',
      properties: {
        file: { type: 'string', description: 'path relative to project root; omit for the workspace' },
        severity: { type: 'string', enum: ['error', 'warning', 'all'], description: 'default all' },
        run_check: { type: 'boolean', description: 'run cargo check first; default true' },
        timeout_ms: { type: 'number', description: 'how long to wait for the check, default 120000' },
      },
    },
    async run(a) {
      if (a.file) await ra.open(a.file);
      if (a.run_check !== false) await ra.runFlycheck(Number(a.timeout_ms) || 120000);
      const want = a.severity === 'error' ? 1 : a.severity === 'warning' ? 2 : 4;
      const target = a.file ? a.file.replace(/\\/g, '/') : null;
      let out = '';
      let n = 0;
      for (const [uri, diags] of ra.diagnostics) {
        const f = fromUri(uri);
        if (target && f !== target) continue;
        const keep = diags.filter((d) => (d.severity || 4) <= want);
        if (!keep.length) continue;
        out += '\n' + f + '\n';
        for (const d of keep) {
          n++;
          const sev = ['', 'error', 'warning', 'info', 'hint'][d.severity || 4];
          const code = d.code ? ' [' + (typeof d.code === 'object' ? d.code.value : d.code) + ']' : '';
          out += '  ' + String(d.range.start.line + 1).padStart(5) + ': ' + sev + ': ' +
            d.message.split('\n')[0] + code + '\n';
        }
      }
      return n ? n + ' diagnostic(s):' + out
        : 'No diagnostics' + (a.file ? ' for ' + a.file : ' in the workspace') + '.';
    },
  },
};

/* --------------------------------------------------------------- MCP layer */

function reply(id, result) {
  process.stdout.write(JSON.stringify({ jsonrpc: '2.0', id, result }) + '\n');
}
function replyError(id, code, message) {
  process.stdout.write(JSON.stringify({ jsonrpc: '2.0', id, error: { code, message } }) + '\n');
}

async function handle(msg) {
  const { id, method, params } = msg;

  if (method === 'initialize') {
    return reply(id, {
      protocolVersion: (params && params.protocolVersion) || '2024-11-05',
      capabilities: { tools: {} },
      serverInfo: { name: 'rust-lsp', version: '1.0.0' },
      instructions:
        'rust-analyzer-backed semantic navigation for this workspace. `line` arguments are 1-based. ' +
        'Most tools accept either a bare `symbol` name or an explicit `file` plus `line`.',
    });
  }
  if (method === 'notifications/initialized' || method === 'initialized') return;
  if (method === 'ping') return reply(id, {});
  if (method === 'tools/list') {
    return reply(id, {
      tools: Object.keys(TOOLS).map((name) => ({
        name,
        description: TOOLS[name].description,
        inputSchema: TOOLS[name].schema,
      })),
    });
  }
  if (method === 'tools/call') {
    const name = params && params.name;
    const tool = TOOLS[name];
    if (!tool) return replyError(id, -32601, 'unknown tool: ' + name);
    try {
      await ra.start();
      const text = await tool.run((params && params.arguments) || {});
      return reply(id, { content: [{ type: 'text', text: String(text) }] });
    } catch (e) {
      return reply(id, { content: [{ type: 'text', text: 'Error: ' + e.message }], isError: true });
    }
  }
  if (id !== undefined) replyError(id, -32601, 'unsupported method: ' + method);
}

let stdinBuf = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', (d) => {
  stdinBuf += d;
  let nl;
  while ((nl = stdinBuf.indexOf('\n')) >= 0) {
    const line = stdinBuf.slice(0, nl).trim();
    stdinBuf = stdinBuf.slice(nl + 1);
    if (!line) continue;
    let msg;
    try { msg = JSON.parse(line); } catch (e) { continue; }
    Promise.resolve(handle(msg)).catch((e) => log('handler error:', e.message));
  }
});
process.stdin.on('end', () => process.exit(0));
process.on('SIGTERM', () => { if (ra.proc) ra.proc.kill(); process.exit(0); });
