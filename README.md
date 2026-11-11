# hermes-cartographer

Code intelligence for [Hermes Agent](https://github.com/NousResearch/hermes-agent):
a token-budgeted repo map, symbol definitions and references, deterministic
first-turn context injection, and AST-safe cross-file rename for Python —
backed by an incremental SQLite index. No embeddings, no network, no model
calls, no shell, no third-party dependencies.

## Install

After the catalog entry merges:

```powershell
hermes plugins install hermes-cartographer
hermes plugins enable hermes-cartographer
```

Before then, from a clone (Windows shown; on macOS/Linux the user plugin
directory is `~/.hermes/plugins`, or `$HERMES_HOME/plugins`):

```powershell
git clone https://github.com/nnazinwaogu/hermes-cartographer
Copy-Item -Recurse .\hermes-cartographer "$env:LOCALAPPDATA\hermes\plugins\hermes-cartographer"
hermes plugins enable hermes-cartographer
```

Start a session inside a repository. With `inject: first` (the default) the
first turn carries whatever the 500 ms indexing budget could map — a partial
map on a cold tree, a one-line hint when nothing was indexed yet. Later turns
refresh incrementally.

## Tools

| Tool | Arguments | Use it when |
| --- | --- | --- |
| `code_map` | `path?`, `budget?`, `subpath?` | First contact with a repo. Replaces reading whole files to learn the layout. |
| `symbol_find` | `name`, `kind?`, `mode?`, `path?`, `limit?` | You know a name and want its `file:line`, kind and signature instead of grepping. |
| `symbol_refs` | `name`, `include_attributes?`, `limit?`, `path?` | Before editing: every call site, AST-precise for Python. |
| `symbol_rename` | `old`, `new`, `dry_run?`, `include_attributes?` | A Python rename that must not touch strings, comments or unrelated names. |

Every tool returns JSON. A failure is `{"error": "...", "hint": "..."}`; no
handler ever raises into the agent loop.

## Commands

`/carto` in chat and `hermes carto` in a terminal share one implementation:

```
carto index [path]                  build or refresh the index
carto map [path] [--budget N]       print a budgeted symbol outline
carto find <name> [path]            find definitions
carto refs <name> [path] [--attrs]  list references
carto stats [path]                  index statistics
carto help                          help
```

Rename is tool-only by design: the dry-run diff and the apply are one
explicit step apart in `symbol_rename`.

## Configuration

| Key | Type | Default | Meaning |
| --- | --- | --- | --- |
| `roots` | list | `[]` | Absolute roots to index. Empty means the session's working directory. |
| `inject` | str | `first` | `first`, `always` or `off` for the `pre_llm_call` repo map. |
| `map_budget` | int | `4000` | Maximum characters injected per turn. |
| `default_map_budget` | int | `6000` | `code_map` budget when the caller passes none. |
| `max_file_kb` | int | `512` | Files larger than this are skipped. |
| `max_files` | int | `20000` | Stop indexing after this many files. |
| `excludes` | list | `[]` | Extra directory names to skip, on top of the built-in list. |

## The 90-second tour

```
# 1  index a real source tree (PowerShell)
$repo = "$env:LOCALAPPDATA\hermes\hermes-agent\tools"
hermes carto index $repo
indexed 378 files · 9,219 symbols · 138,317 refs · 10,456 ms

# 2  ask the agent instead of grepping
hermes chat --in .\tests\fixtures\project_a -q "Use symbol_find to locate class Engine. Reply with file:line only." --oneshot
core.py:6

# 3  locate a definition without grep
hermes carto find dispatch $repo
async_delegation_worker.py:43  method WorkerDelegationLedger.dispatch(self, record)
browser_use_cli.py:837  method browser_exec.dispatch()
code_kernel.py:224  method CellAuthority.dispatch(self, tool_name: str, tool_args: dict)
registry.py:1069  method ToolRegistry.dispatch(self, name: str, args: dict, *, scope: Optional[str]=None, **kwargs)

# 4  references before an edit
hermes carto refs dispatch $repo
browser_use_cli.py:861:63  dispatched = run_fenced({"features": {"local": True}}, dispatch)
browser_use_cli.py:863:21  dispatched = dispatch()
code_execution_rpc.py:106:21  result = dispatch(tool_name, tool_args)
…
(scanned 1 non-Python files)

# 5  what the index holds
hermes carto stats $repo
files: 378  symbols: 9219  refs: 138317
languages: other 1, python 377
kinds: class 368, constant 2129, function 4903, method 1819
last index: 2026-11-11T04:17:54+00:00 (10456 ms)
```

`stats` also prints the absolute root and index paths; the counts above are
from the captured run.

Inside a chat session the same facts are four tool calls, and `symbol_rename`
adds the diff-first apply step.

## Limits

- **Python is AST-precise.** Symbols, references and rename come from `ast`.
- **Other languages are definitions-only.** JavaScript, TypeScript, Go, Rust,
  Java, C/C++/C# get a line-based regex scan; `symbol_refs` for them is a
  whole-word on-disk scan (20 MB cap), and rename is refused.
- **No type inference, no call graph.** `symbol_refs` is name-based.
- **Rename scope.** Import aliases, `global`/`nonlocal`, `except ... as`,
  match-pattern names and keyword arguments (`f(old=1)`) produce warnings
  rather than edits. Methods always rewrite `obj.old(...)` call sites; other
  attributes need `include_attributes=true`.
- **Rename authority.** `symbol_rename` edits files under the `path` you pass
  — the same filesystem authority as the agent's edit tools — and writes
  nothing unless `dry_run` is explicitly `false`.
- **Index caps.** Excluded directories, a 512 KB per-file cap and a 20,000
  file cap apply. A file that does not parse contributes no symbols and does
  not abort the sync.
- **Incremental by `(size, mtime_ns)`.** Unchanged files are never re-read;
  each tool call re-stats the tree. A build that preserves both size and
  mtime is not noticed until the file changes or the index is rebuilt.
- **Where the index lives.** One SQLite file per root under
  `plugin-data/hermes-cartographer/`; its size tracks the reference count
  (23 MB for 378 files, hundreds of MB for a very large tree). Delete the
  file to reclaim the space; the next call rebuilds it.
- **The hook maps the session's working directory** when `roots` is empty.
  Start Hermes inside the repo you mean to map, or set `roots`. Starting it
  in a large non-repository directory makes the first tool call index that
  whole directory.

## Privacy and disclosure

The plugin reads source files under the roots you configure and writes only
its own SQLite index under `plugin-data/hermes-cartographer/`. It makes no
network requests, spawns no shell, calls no model, and has no third-party
dependencies.

## Validation

```
$ hermes plugins validate . --install-deps
✓ manifest — plugin.yaml parses
✓ manifest fields — name, version, description present
✓ requires_hermes — spec '>=0.23.0' parses
✓ config schema — shape valid
✓ requires_env — all entries UPPER_SNAKE
✓ oauth — not declared
✓ loadable — entry: __init__.py
✓ python dependencies — none declared
✓ capability probe — register() ran in isolation
✓ declared tools — matches registrations
✓ declared hooks — matches registrations
✓ declared middleware — matches registrations
✓ built-in tool collisions — no collisions
✓ security scan — safe
✓ no core override — no runtime rebinds of Hermes core
◆ Isolation — runs in the plugin host (plugins.isolation: host)
  · ctx.register_cli_command() is skipped in the host (`hermes <command>` 
subcommands are wired into the local CLI parser)

Validation passed.

$ hermes plugins doctor . --ci
  manifest: hermes-cartographer 1.0.0 (standalone)
  OK: runtime discovery, manifest parsing, import, and registration passed
  registrations: 4 tool(s), 1 hook(s)
```

## Development

Stdlib only; tests are `unittest`:

```powershell
PS> python -m unittest discover -s tests -v
...
Ran 93 tests in 5.8s

OK

PS> hermes plugins validate . --install-deps    # Validation passed.
PS> hermes plugins doctor . --ci                # 4 tool(s), 1 hook(s)
```

Layout: `carto/` is the library (importable without Hermes), `tools.py` the
four handlers, `__init__.py` registration + hook + `/carto` + `hermes carto`,
`skills/cartographer/SKILL.md` the bundled usage skill.

## License

MIT. See [LICENSE](LICENSE).
