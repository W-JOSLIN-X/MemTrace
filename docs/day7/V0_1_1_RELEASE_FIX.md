# MemTrace v0.1.1 release fix decision

Status: implementation and release-gate evidence in progress on
`codex/v0.1.1-release-fix`.

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
