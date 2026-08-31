# MemTrace v0.1.1 release fix decision

Status: implementation and final local release-gate evidence passed on
`codex/v0.1.1-release-fix`; the owner signing key is registered and verified.
The ordinary main push and signed `v0.1.1` tag remain pending.

## Why v0.1.1 is required

The immutable historical `v0.1.0` tag has two production blockers:

1. `git verify-tag v0.1.0` reports that the tag has no cryptographic
   signature, while the deployment policy requires a verifiable release tag.
2. The application intentionally ignored forwarded headers, but the release
   topology puts host Nginx in front of a loopback-published Docker port. In
   that topology the API cannot distinguish Internet clients for auth
   rate-limiting unless it accepts the client address from a strictly trusted
   proxy boundary.

The old tag must not be deleted, moved, re-signed or otherwise rewritten.
Production deployment moves to a new `v0.1.1` candidate after its own gates
pass and its signature is independently verifiable.

## Frozen security decision

- Nginx overwrites `X-Forwarded-For` with `$remote_addr`; it never appends a
  client-supplied chain.
- The release Compose network has an explicit bridge gateway. Uvicorn accepts
  proxy headers only from that exact gateway via `TRUSTED_PROXY_IPS`.
- `TRUSTED_PROXY_IPS` accepts exact IPv4/IPv6 addresses only. Wildcards,
  networks/CIDRs, hostnames, scoped addresses, malformed and empty entries are
  rejected.
- A production container without a non-empty trusted proxy allowlist exits
  before database migration or server startup.
- A direct or test process without a trusted proxy allowlist runs with proxy
  header handling explicitly disabled.
- Uvicorn access logging is disabled because request lines can contain memory
  search text. The supplied Nginx access format records only controlled
  metadata and `$uri`, never query arguments, cookies or bodies; Nginx error
  logging is critical-only.

## Compatibility

- Public wire contract remains `2.1.0`.
- Database head remains `007_day7_public_release`; no migration is needed.
- Release/application/image version becomes `0.1.1`.
- Existing G1-G5 APIs and stored data are unchanged.

## Required evidence before remote release

- exact-proxy and forged-forwarded-header integration tests;
- full backend, frontend, OpenAPI and migration gates;
- release Compose rendering and Docker cold-start/restart checks;
- actual Nginx-to-container peer address equals the configured exact gateway;
- two distinct synthetic client addresses receive independent auth rate-limit
  buckets, while an untrusted peer cannot spoof them;
- metadata-only log scan;
- signed annotated `v0.1.1` verifies with `git verify-tag` and resolves to the
  same fully tested commit as remote `main`.

## Targeted local evidence completed on 2026-08-31

- Backend: `509 passed`; pip check, Ruff check and Ruff format check exited 0.
- Frontend: 19 test files / 84 tests passed; typecheck, lint and production
  build exited 0.
- Contract/migration: OpenAPI exported twice with identical SHA-256
  `63B4CB3BC8CB181B8498521A30729ED1C1B318F4CEB77C6492EA26EC9A771797`;
  the unique head is `007_day7_public_release`, and fresh
  `006 -> 007 -> 006 -> 007` passed.
- Release signing: GitHub signing-key ID `1145825` is registered to
  `W-JOSLIN-X`; the uploaded ED25519 public-key fingerprint is
  `SHA256:7FT18rpSw1149vdlv5KHU0SNd3mDZldp0Fk2te7LInE`, exactly matching the
  repository allowlist and the locally verified signing key. No private-key
  material was read, printed or uploaded.
- Real Provider preflight: 6/6 passed with `provider_mode=real`, model
  `deepseek-v4-flash`, strict Schema, streaming, function calling and actual
  non-fabricated usage.
- Docker image `memtrace:0.1.1` passed cold start, restart and down/up with
  retained volumes. A real post-restart turn reported actual chat usage and
  did not fall back to Mock. Immediately before publication the image is
  rebuilt from the final candidate and its OCI revision must equal that exact
  candidate HEAD.
- The live release network was `172.31.247.0/28` with gateway
  `172.31.247.1`. Host-originated forwarded clients kept independent rate-limit
  buckets; a same-network untrusted peer changing its forwarded header received
  `401,401,401,401,401,429`.
- The supplied template passed `nginx -t` in official Nginx 1.31.4. Container
  log scans found no Key, session secret, account password, synthetic prompt or
  Uvicorn request line.
- Trivy 0.73.0 with its 2026-08-31 database reported zero fixable HIGH/CRITICAL
  findings. The ignored CycloneDX SBOM SHA-256 is
  `5333BDCF0D25909A901ABF3BD8EA92ACA4F6347085E65E3E5E98624E92F79122`.

These are new v0.1.1 engineering and targeted real-Provider regression facts.
They do not relabel the historical Day 7 64-workflow artifact as a new run. A
final signed release must rerun whatever broader semantic/browser gates the
owner selects for publication and record that evidence separately.
