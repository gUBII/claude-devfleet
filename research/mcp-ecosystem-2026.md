# MCP Ecosystem — State of the World, May 2026

## Executive Summary

**What is stable**
- **stdio transport** — unchanged, still the recommended default for local subprocess servers. DevFleet's `mcp_context` and `mcp_devfleet` are on the correct side of the spec.
- **MCP Python SDK v1.x line** — actively maintained as the supported stable channel through 2026; current release is **v1.27.1** (May 8, 2026). Pin `mcp>=1.25,<2`.
- **Streamable HTTP** — the only blessed network transport in spec `2025-11-25`. Claude Code, Cursor, Continue, Cline all support it natively.

**What is changing**
- **HTTP+SSE legacy transport** is officially deprecated. Vendor cutoffs landing now (Keboola: Apr 1 2026; Atlassian Rovo: Jun 30 2026).
- **MCP Python SDK v2** is pre-alpha on `main` with a heavy transport-layer rewrite — Q1 2026 target slipped.
- **Resources** are gaining serious adoption for read-only data; community consensus is firm — Resources for data, Tools for actions.

## 1. Streamable HTTP vs SSE

From the [current spec (2025-11-25)](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports): "The protocol currently defines two standard transport mechanisms: stdio and Streamable HTTP." Streamable HTTP "replaces the HTTP+SSE transport from protocol version 2024-11-05."

SSE survives only as a backwards-compat fallback: clients MAY probe Streamable HTTP first and fall back to SSE on 400/404/405 ([fka.dev](https://blog.fka.dev/blog/2025-06-06-why-mcp-deprecated-sse-and-go-with-streamable-http/), [Auth0](https://auth0.com/blog/mcp-streamable-http/)).

Concrete vendor cutoffs:
- **Keboola** — SSE removed **Apr 1, 2026** ([changelog](https://changelog.keboola.com/sse-transport-deprecation-migration-to-streamable-http/))
- **Atlassian Rovo** — SSE removed **Jun 30, 2026** ([notice](https://community.atlassian.com/forums/Atlassian-Remote-MCP-Server/HTTP-SSE-Deprecation-Notice/ba-p/3205484))
- Python SDK deprecation tracked at [python-sdk issue #2278](https://github.com/modelcontextprotocol/python-sdk/issues/2278)

Client support, May 2026: Claude Code Streamable-HTTP native ([Anthropic docs](https://code.claude.com/docs/en/mcp)); Cursor native; Continue and Cline both support it; Claude Desktop still stdio-default and reaches remote servers via `mcp-remote` bridge ([systemprompt.io](https://systemprompt.io/guides/claude-code-mcp-servers-extensions), [MCPCore](https://mcpcore.io/blog/how-to-connect-claude-cursor-windsurf-to-mcp-server)). **No major client requires SSE anymore.**

## 2. MCP Python SDK Cadence

Branch split happened at **v1.25** (Dec 18, 2025): `main` is v2 pre-alpha, `v1.x` is maintained stable. Pin `mcp>=1.25,<2`.

v1.x last 6 months ([releases page](https://github.com/modelcontextprotocol/python-sdk/releases), [Speakeasy](https://www.speakeasy.com/mcp/release-notes)):
- **v1.23.0** (Dec 2, 2025) — Spec 2025-11-25; Sampling with Tools (SEP-1577), Tasks (SEP-1686), URL-based client ID (SEP-991), tool name validation (SEP-986)
- **v1.24.0** (Dec 12, 2025) — Custom httpx.AsyncClient injection
- **v1.25.0** (Dec 18, 2025) — Branch split; v1.x → maintenance mode
- **v1.26.0** (Jan 24, 2026) — Resource/ResourceTemplate metadata backport
- **v1.27.0** (Apr 2, 2026) — StreamableHTTP idle timeout, **RFC 8707 OAuth resource validation**
- **v1.27.1** (May 8, 2026) — Pydantic 2.13 compat, OAuth metadata coercion

**No breaking changes inside v1.x.** v2 will rewrite the transport layer substantially ([ContextStudios](https://www.contextstudios.ai/blog/mcp-ecosystem-in-2026-what-the-v127-release-actually-tells-us)). FastMCP powers ~70% of Python servers but is a higher-level wrapper *over* the official SDK ([Apigene](https://apigene.ai/blog/fastmcp)) — using the raw SDK in DevFleet is fine.

## 3. Resources vs Tools

Consensus heuristic ([Speakeasy](https://www.speakeasy.com/mcp/core-concepts/resources), [Zuplo](https://zuplo.com/blog/mcp-resources), [Kubaski](https://medium.com/@laurentkubaski/mcp-resources-explained-and-how-they-differ-from-mcp-tools-096f9d15f767)):
- **Tools** = model-controlled actions
- **Resources** = application-controlled URI-addressable read-only data

> "Define resources according to what the client should know and tools according to what the client can do."

Leading servers: filesystem/git/database/KB servers use Resources heavily; API-wrapper servers (Slack, GitHub, Jira) remain tool-shaped. Common antipattern called out by [Itential](https://www.itential.com/blog/company/itential-mcp/designing-mcp-servers-for-infrastructure/) and [Docker](https://www.docker.com/blog/mcp-server-best-practices/): mapping every REST endpoint to a tool. Replace with outcome-oriented tools + Resources for browseable state.

**DevFleet impact**: `mcp_context.get_mission_context`, `get_project_context`, `get_session_history`, `read_past_reports`, `get_team_context` are all read-only URI-addressable — textbook Resources. `mcp_devfleet.submit_report` / `create_sub_mission` are correctly tools.

## 4. Registries & Discovery

[Official registry at `registry.modelcontextprotocol.io`](https://registry.modelcontextprotocol.io/) — maintained by Anthropic + GitHub + PulseMCP + Microsoft as a metaregistry.

Third-party landscape ([TrueFoundry](https://www.truefoundry.com/blog/best-mcp-registries), [Apigene](https://apigene.ai/blog/mcp-marketplace)):
- **Glama** — 6,000+ listings, best metadata
- **mcp.so** — 5,000+
- **Smithery** — 2,000–7,000, best CLI install flow ([mcpmarket.com/server/smithery-cli](https://mcpmarket.com/server/smithery-cli))
- **mcpservers.org** — 4,000+
- **MCPMarket.com** — 10,000+ across 23 categories
- **mcp.run** — runtime-focused

Discovery quality remains poor — duplicated entries, stale metadata, unsigned packages ([Medium roundup](https://medium.com/demohub-tutorials/17-top-mcp-registries-and-directories-explore-the-best-sources-for-server-discovery-integration-0f748c72c34a)). DevFleet's stdio servers don't need to be registered. `mcp_external.py` should be listed on the official registry if it's intended for third-party agents.

## 5. Security for HTTP-Mounted MCP

**Spec MUST-level requirements** for Streamable HTTP servers:
> "Servers MUST validate the `Origin` header on all incoming connections to prevent DNS rebinding attacks."
> "When running locally, servers SHOULD bind only to localhost (127.0.0.1) rather than all network interfaces (0.0.0.0)."
> "Servers SHOULD implement proper authentication for all connections."

Production auth pattern in 2026: **OAuth 2.1 + RFC 8707 resource validation** (added to SDK in v1.27.0). For internal/B2B, header-token over HTTPS is acceptable if scoped and rotated ([Practical DevSecOps](https://www.practical-devsecops.com/mcp-security-guide/)). [Composio](https://composio.dev/content/mcp-vulnerabilities-every-developer-should-know): "Many public MCP servers do not verify requests… some accept unauthenticated calls." Rate limiting universally required across all 2026 write-ups ([OWASP Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/MCP_Security_Cheat_Sheet.html)).

The threat model that emerged: **MCP servers are public-facing API endpoints attached to high-privilege agent identities**. The early ecosystem habit of "it's just for AI, skip auth" is the root cause of most CVEs.

## 6. Cautionary Tales

- **MCPTox benchmark** — 45 live MCP servers tested; >60% attack success on many, peak 72% via tool-description prompt injection ([ITECS](https://itecsonline.com/post/mcp-tool-poisoning-enterprise-ai-agent-security-2026)).
- **GitHub MCP Prompt Injection Heist** (May 2025) — Legitimate server, attackers planted injection in public GitHub issues; broad-scoped PATs let agents exfiltrate private repo data to public PRs. Fix: scope tokens narrowly, sandbox cross-resource transitions, Docker MCP Gateway introduced *interceptors* ([Docker](https://www.docker.com/blog/mcp-horror-stories-github-prompt-injection/)).
- **CVE-2025-6514** — `mcp-remote` OAuth proxy RCE, **437,000+ environments** ([Network Intelligence](https://www.networkintelligence.ai/blogs/model-context-protocol-mcp-security-checklist/)).
- **First in-the-wild malicious MCP server** (Sept 25, 2025) — Backdoored package, ~300 organizations integrated ([Securelist](https://securelist.com/model-context-protocol-for-ai-integration-abused-in-supply-chain-attacks/117473/)).
- **"Mother of All AI Supply Chains"** (Apr 2026) — Design-level RCE in Anthropic SDK across languages; 7,000+ public servers + 150M+ downloads exposed ([OX Security](https://www.ox.security/blog/the-mother-of-all-ai-supply-chains-critical-systemic-vulnerability-at-the-core-of-the-mcp/), [SecurityWeek](https://www.securityweek.com/by-design-flaw-in-mcp-could-enable-widespread-ai-supply-chain-attacks/)).
- **H1 2026 CVE roll-up** — CVSS 9.0+ on LibreChat (CVE-2026-22252), WeKnora (CVE-2026-22688), `@akoskm/create-mcp-server-stdio` (CVE-2025-54994), Cursor (CVE-2025-54136), MCP Inspector (CVE-2025-49596) ([PipeLab](https://pipelab.org/blog/state-of-mcp-security-2026/)).

## Direct Recommendations for DevFleet

1. **Pin SDK explicitly.** `backend/requirements.txt` → `mcp>=1.25,<2`. Gets you OAuth + idle-timeout fixes from v1.27.x.
2. **Add auth on `/mcp` immediately.** Plan/dispatch/cancel are state-changing — header-token (`X-DevFleet-Token`) minimum, OAuth 2.1 + RFC 8707 ideal.
3. **Validate `Origin` and bind correctly.** Spec MUST. Container binds `0.0.0.0` (Docker) — without origin validation, this is a DNS-rebinding bug and a spec violation today.
4. **Set a removal date on `/mcp/sse`.** Suggest July 1, 2026 (aligned with Atlassian Rovo). Log deprecation warning on every SSE connection, then delete.
5. **Migrate `mcp_context` read paths to Resources.** Expose `devfleet://mission/{id}/context`, `devfleet://session/{id}/history`, etc. as URI-addressable Resources. Keep `mcp_devfleet` as Tools (they're actions).
6. **Treat tool descriptions as security-relevant.** Audit description strings in all three servers for prompt-injection bait. Add a CI diff-check on description changes.
7. **Rate-limit `/mcp`.** `slowapi` middleware on FastAPI, per-token bucket. Pair with #2.
8. **Plan v2 upgrade — don't rush.** v1.x maintained through 2026. Budget a focused sprint when v2 ships stable; do not adopt pre-alpha for production fleet.

## Sources

Spec & SDK: [Spec 2025-11-25](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports), [python-sdk releases](https://github.com/modelcontextprotocol/python-sdk/releases), [SSE deprecation issue #2278](https://github.com/modelcontextprotocol/python-sdk/issues/2278), [Official MCP Registry](https://registry.modelcontextprotocol.io/)

Transport: [fka.dev](https://blog.fka.dev/blog/2025-06-06-why-mcp-deprecated-sse-and-go-with-streamable-http/), [Auth0](https://auth0.com/blog/mcp-streamable-http/), [Atlassian](https://community.atlassian.com/forums/Atlassian-Remote-MCP-Server/HTTP-SSE-Deprecation-Notice/ba-p/3205484), [Keboola](https://changelog.keboola.com/sse-transport-deprecation-migration-to-streamable-http/), [Toolradar](https://toolradar.com/blog/streamable-http-vs-sse), [Cloudflare Agents](https://developers.cloudflare.com/agents/model-context-protocol/transport/)

SDK cadence: [Speakeasy](https://www.speakeasy.com/mcp/release-notes), [ContextStudios](https://www.contextstudios.ai/blog/mcp-ecosystem-in-2026-what-the-v127-release-actually-tells-us), [TokenMix](https://tokenmix.ai/blog/mcp-updates-changelog-every-protocol-change-2026), [v1→v2 Medium](https://medium.com/the-ai-language/mcp-is-migrating-from-version-1-to-version-2-07f4cc7624fb), [FastMCP changelog](https://gofastmcp.com/changelog), [Apigene FastMCP](https://apigene.ai/blog/fastmcp)

Clients: [Anthropic docs](https://code.claude.com/docs/en/mcp), [systemprompt.io](https://systemprompt.io/guides/claude-code-mcp-servers-extensions), [MCPCore](https://mcpcore.io/blog/how-to-connect-claude-cursor-windsurf-to-mcp-server)

Server design: [philschmid](https://www.philschmid.de/mcp-best-practices), [Speakeasy Resources](https://www.speakeasy.com/mcp/core-concepts/resources), [Zuplo Resources](https://zuplo.com/blog/mcp-resources), [Kubaski](https://medium.com/@laurentkubaski/mcp-resources-explained-and-how-they-differ-from-mcp-tools-096f9d15f767), [Itential](https://www.itential.com/blog/company/itential-mcp/designing-mcp-servers-for-infrastructure/), [Docker best practices](https://www.docker.com/blog/mcp-server-best-practices/)

Registries: [TrueFoundry](https://www.truefoundry.com/blog/best-mcp-registries), [Apigene marketplace](https://apigene.ai/blog/mcp-marketplace), [Composio Smithery](https://composio.dev/content/smithery-alternative), [17+ registries roundup](https://medium.com/demohub-tutorials/17-top-mcp-registries-and-directories-explore-the-best-sources-for-server-discovery-integration-0f748c72c34a)

Security: [OWASP](https://cheatsheetseries.owasp.org/cheatsheets/MCP_Security_Cheat_Sheet.html), [Network Intelligence](https://www.networkintelligence.ai/blogs/model-context-protocol-mcp-security-checklist/), [Practical DevSecOps guide](https://www.practical-devsecops.com/mcp-security-guide/), [Practical DevSecOps vulns](https://www.practical-devsecops.com/mcp-security-vulnerabilities/), [Composio vulns](https://composio.dev/content/mcp-vulnerabilities-every-developer-should-know), [Security Boulevard](https://securityboulevard.com/2026/04/7-mcp-authentication-vulnerabilities-b2b-saas-vendors-must-prevent/)

Incidents: [Docker GitHub heist](https://www.docker.com/blog/mcp-horror-stories-github-prompt-injection/), [Securelist](https://securelist.com/model-context-protocol-for-ai-integration-abused-in-supply-chain-attacks/117473/), [OX "Mother of All"](https://www.ox.security/blog/the-mother-of-all-ai-supply-chains-critical-systemic-vulnerability-at-the-core-of-the-mcp/), [OX RCE roll-up](https://www.ox.security/blog/mcp-supply-chain-advisory-rce-vulnerabilities-across-the-ai-ecosystem/), [SecurityWeek](https://www.securityweek.com/by-design-flaw-in-mcp-could-enable-widespread-ai-supply-chain-attacks/), [Hacker News](https://thehackernews.com/2026/04/anthropic-mcp-design-vulnerability.html), [ITECS](https://itecsonline.com/post/mcp-tool-poisoning-enterprise-ai-agent-security-2026), [PipeLab](https://pipelab.org/blog/state-of-mcp-security-2026/), [Doppler](https://www.doppler.com/guides/mcp-server-security-risks-attack-scenarios/malicious-code-and-credential-theft)
