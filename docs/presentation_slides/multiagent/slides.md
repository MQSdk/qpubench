---
title: "Lean Agent Code & Multi-Agent Systems"
subtitle: "Ponytail · gitea-mcp · Claude Code · Self-Hosted LLMs"
author: "MQS · mark@mqs.dk"
date: "2026"
institute: "Modular Quantum Solutions"
theme: "metropolis"
fonttheme: "professionalfonts"
monofont: "DejaVu Sans Mono"
monofontoptions: "Scale=0.78"
aspectratio: 169
section-titles: true
toc: false
colorlinks: true
header-includes:
  - \metroset{block=fill}
  - \setbeamertemplate{navigation symbols}{}
  - \usepackage{booktabs}
  - \usepackage{amsmath,amssymb}
---

# Lean Agent Code

## Why Code Quality Matters for AI Agents

**The problem**: AI agents tend to over-engineer — adding layers, abstractions, and boilerplate that create maintenance debt without adding value.

**Research findings on AGENTS.md / code-guidance files**:

| Intervention | Compliance |
|---|---|
| Documentation alone | ~25–40% |
| Runtime enforcement hooks | ~95% |
| Auto-generated AGENTS.md | *reduces* success rate by ~3% |

\vspace{0.3em}
\begin{block}{Conclusion}
Rules without enforcement drift. The solution is a decision ladder baked into every coding session.
\end{block}

## Ponytail Decision Ladder

Before writing a single line of code, an AI agent asks:

1. **Does it need to exist?** — skip if not required
2. **Already in codebase?** — reuse existing code
3. **Stdlib handles it?** — prefer standard library
4. **Native platform feature?** — use platform primitives
5. **Installed dependency?** — use what's already there
6. **One line?** — write one line
7. **Then**: minimum viable implementation

\vspace{0.3em}
\begin{block}{Non-negotiable}
Validation, error handling, security, and accessibility are always kept — ponytail targets complexity, not safety.
\end{block}

## Ponytail in Practice — QPUBench Examples

Fixes made during QPUBench development under ponytail review:

| File | Issue | Fix |
|---|---|---|
| `store.py` `ParquetStore.query` | `pd.Series` mask — bug + unnecessary | Replaced with `df = df[df[col] == val]` loop |
| `stub.py` `StubMBQCAdapter.spec` | `pattern = None` — dead variable | Removed |
| `adapter.py` (qforte) | `tuple([sym, tuple(xyz)])` — list wrapped in tuple | Changed to `(sym, tuple(xyz))` |
| `store.py` `_iter` | No return type | Added `-> Iterator[BenchmarkRecord]` |
| `record.py` `_utcnow` | Lambda assigned to name (noqa E731) | Converted to typed `def` |

**Result**: fewer lines, cleaner types, one real bug found.

## Python Quality Toolchain — QPUBench

\footnotesize
```bash
ruff check src/ tests/    # lint (line-length 100, target py311)
ruff format src/ tests/   # format
mypy src/                 # static types (strict = true)
pytest tests/ -q          # 259 tests, SDK-dependent ones skip cleanly
```

| Tool | Role |
|------|------|
| **Pydantic v2** | Runtime-validated schemas — field types enforced at parse time |
| **ruff** | Linting + auto-formatting, replaces flake8/isort/black |
| **mypy strict** | Full type coverage — `Any` only where unavoidable |
| **pytest** | Schema-only test suite runs with `pip install .` alone |
\normalsize

## Ponytail — Install & Use

```bash
# Claude Code plugin
/plugin install ponytail@ponytail

# Review current diff for over-engineering
/ponytail-review

# Scan entire repo for unnecessary code
/ponytail-audit

# Collect deferred optimisation shortcuts
/ponytail-debt
```

**Supported agents**: Claude Code · OpenAI Codex · GitHub Copilot CLI · Cursor · Windsurf · Gemini CLI · Devin

\vspace{0.3em}
*github.com/DietrichGebert/ponytail*

# Multi-Agent System

## Why Multi-Agent?

**Single-agent limitation**: one agent, one context window, one repo at a time.

**Multi-agent enables**:

- Parallel work across multiple repos or services
- Specialised agents per domain (schemas · adapters · tests · docs)
- Continuous background tasks (CI watching, PR review, dependency updates)
- Self-hosted pipelines with no cloud data exposure

\vspace{0.3em}

```
User
 └── Orchestrator agent
         ├── Schema agent     (qpubench schemas)
         ├── Adapter agent    (integrations/)
         └── Review agent     (tests + AGENTS.md checks)
```

## gitea-mcp Integration

**gitea-mcp** connects AI agents directly to Gitea repositories via MCP

```
AI Agent (Claude Code / Cursor / Windsurf)
    └── MCP protocol
            └── gitea-mcp server  (gitea.com/gitea/gitea-mcp)
                    └── Gitea REST API
                            └── repos · issues · PRs · wikis · CI
```

- Official MCP server from the Gitea project
- Agents can read/write code, open PRs, comment on issues, trigger CI
- Works with Claude Code, Mistral Vibe, Gemini CLI, OpenCode, Devin
- Self-hosted Gitea = full data sovereignty

## Supported Agents & Platforms

| Agent | Open-weight | Self-hostable | gitea-mcp |
|---|---|---|---|
| Claude Code (Anthropic) | No | No | Yes |
| Mistral Vibe | Yes | Yes | Yes |
| Gemini CLI (Google) | No | No | Yes |
| GitHub Copilot CLI | No | No | Yes |
| OpenCode | Depends | Yes | Yes |
| Devin | No | No | Yes |

\vspace{0.3em}
All agents read the same `AGENTS.md` file — one set of rules, any tool.

## Claude Code + Mistral Vibe

:::::: {.columns}
::: {.column width="50%"}
**Claude Code** *(Anthropic)*

- CLI-first agentic coding assistant
- `CLAUDE.md` / `AGENTS.md` for persistent rules
- Git worktrees for isolated parallel agents
- Per-project memory system across sessions
- Hooks for automated validation
:::
::: {.column width="50%"}
**Mistral Vibe** *(Mistral AI)*

- Open-weight models, self-hostable
- MCP-compatible via gitea-mcp
- Suitable for offline / air-gapped environments
- No data leaves your infrastructure
:::
::::::

\vspace{0.3em}
Both integrate with the same `AGENTS.md` instruction file.

## Context & Memory Management

**Per-session context discipline**:

| File | Purpose |
|------|---------|
| `AGENTS.md` | Language-agnostic, permanent agent instructions |
| `CLAUDE.md` | Claude-specific rules, project conventions |
| `CONTEXT.md` | Current task, status, constraints — written before each session |

**Workflow**:

- Before starting → write `CONTEXT.md` with current task + constraints
- Each session → `"Read CONTEXT.md and CLAUDE.md first"`
- When switching repos → update `CONTEXT.md` with what was just completed
- Parallel agents → clear boundary definitions + shared `contract.ts`

## Multi-Agent Memory Architecture

**Four persistent memory types** (survive across sessions):

| Type | Content | When to save |
|------|---------|--------------|
| `user` | Role, expertise, preferences | First conversation |
| `feedback` | Corrections + validated approaches | After any feedback |
| `project` | Goals, deadlines, decisions | When context changes |
| `reference` | External system pointers | When a resource is named |

```
~/.claude/projects/<repo>/memory/
├── MEMORY.md            <- index (always loaded, max 200 lines)
├── user_role.md
├── feedback_testing.md
└── project_schema.md
```

## Self-Deployed LLMs

**Abzu** (HuggingFace) — open-weight models for quantum computing tasks

- Local deployment via HuggingFace `transformers` / Ollama / vLLM
- No data leaves your infrastructure
- Suitable for air-gapped laboratory environments
- Combine with self-hosted Gitea + gitea-mcp for a fully sovereign pipeline

\vspace{0.3em}

```
Local LLM (Ollama / vLLM)
    └── MCP client (Claude Code / Cursor)
            └── gitea-mcp  -->  Gitea (self-hosted)
                                    └── qpubench repo
```

\begin{block}{Full self-hosted stack}
Model · version control · CI · agent memory — nothing leaves your network.
\end{block}

# Summary

## Key Takeaways

:::::: {.columns}
::: {.column width="50%"}
**Lean code (ponytail)**

- Decision ladder before every change
- Runtime enforcement >> documentation
- Remove dead code ruthlessly
- Type hints everywhere
- 46% fewer lines, 22% fewer tokens
:::
::: {.column width="50%"}
**Multi-agent systems**

- gitea-mcp bridges agents to Gitea
- Same `AGENTS.md` for all tools
- `CONTEXT.md` per session
- Four memory types persist state
- Full self-hosted stack possible
:::
::::::

\vspace{0.3em}

**Links**: `github.com/DietrichGebert/ponytail` · `gitea.com/gitea/gitea-mcp` · `huggingface.co/Abzu`
