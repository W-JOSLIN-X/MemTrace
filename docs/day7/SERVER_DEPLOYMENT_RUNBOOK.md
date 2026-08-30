# MemTrace v0.1.0 server deployment runbook

Status: prepared during Day 7; no server action has been performed.

This runbook applies only to the immutable annotated tag `v0.1.0` after the owner report proves that remote `main` and the tag resolve to the same verified commit. Do not deploy an uncommitted checkout, a moving branch, or a locally rebuilt tree with unknown changes.

## 1. Inputs that must be confirmed before deployment

Record these facts in the deployment log before logging in to the server:

- server provider, region, OS/version, CPU architecture, vCPU, RAM, disk and free space;
- SSH account and key owner;
- domain, DNS provider, current A/AAAA records and change authority;
- current reverse proxy, certificate issuer and renewal method;
- Docker Engine and Compose plugin versions;
- image transfer method: build on server, signed archive, or authenticated registry;
- backup destination, retention period, restore owner and recovery-time objective;
- exact DeepSeek model verified by the Day 7 preflight and available quota;
- maintenance window and rollback decision-maker.

The operator must log in to GitHub/registry, server, DNS or certificate systems through their normal authenticated route. If any required login is unavailable, stop; do not replace it with an unauthenticated mirror or alternate service.

Minimum recommended starting capacity for a single-process SQLite release is 2 vCPU, 4 GiB RAM and 20 GiB persistent SSD. This is an operational starting point, not a measured capacity guarantee; load-test the actual server before raising public invite volume.

## 2. Verify the release source

On a trusted workstation:

```powershell
git fetch --prune origin --tags
$main = git rev-parse origin/main
$tag = git rev-list -n 1 v0.1.0
if ($main -ne $tag) { throw 'main and v0.1.0 differ' }
git verify-tag v0.1.0
git status --short
```

Record the full SHA. The working tree must be clean. If the tag is missing, unsigned/unverifiable under the project policy, or points elsewhere, stop the deployment.

## 3. Server layout and permissions

Use a dedicated unprivileged deployment account and an application directory such as `/opt/memtrace`. Keep these paths outside the source checkout:

```text
/opt/memtrace/release/                 exact v0.1.0 checkout or verified bundle
/opt/memtrace/secrets/llm_api_key      mode 0400
/opt/memtrace/secrets/session_secret   mode 0400
/opt/memtrace/backups/                 encrypted/restricted backup target
/opt/memtrace/deploy/                  metadata-only deployment logs
```

Generate `session_secret` from at least 32 cryptographically random bytes. Store the DeepSeek Key and session secret as files; do not put their values in shell history, `.env`, Compose YAML, image layers, URLs or tickets.

The SQLite data and backup paths are named Docker volumes in `compose.release.yaml`. The container runs as UID/GID 10001, read-only, with all Linux capabilities dropped. Validate volume ownership before first start; do not solve permission errors by making the data world-writable.

## 4. Production configuration

Set only metadata and secret-file paths in the deployment process:

```bash
export APP_REVISION='<full v0.1.0 commit SHA>'
export PUBLIC_ORIGIN='https://memtrace.example.com'
export LLM_MODEL='<Day 7 live-verified model>'
export LLM_API_KEY_FILE='/opt/memtrace/secrets/llm_api_key'
export SESSION_SECRET_FILE='/opt/memtrace/secrets/session_secret'
export COOKIE_SECURE='true'
export MEMTRACE_PORT='18070'
```

Do not set `MOCK_MODE` or `ALLOW_DEMO_SESSIONS`; release Compose fixes both to `false`. Keep the selected memory configuration at `0.85`, `100/300` unless a later version includes a new frozen validation artifact.

Render and inspect the Compose model without printing secret file contents:

```bash
docker compose -p memtrace-release -f compose.release.yaml config
```

Required facts in the rendered model:

- image `memtrace:0.1.0`;
- host bind `127.0.0.1:18070` only;
- `provider_mode=real` inputs;
- demo sessions disabled;
- both secrets mounted under `/run/secrets`;
- named data and backup volumes;
- non-root, read-only, capability-drop and no-new-privileges controls.

## 5. Build or import the image

If building on the target server:

```bash
docker compose -p memtrace-release -f compose.release.yaml build --pull
docker image inspect memtrace:0.1.0 --format '{{json .Config.Labels}}'
```

Confirm OCI version `0.1.0`, revision equals the full tag SHA, and source matches the official repository. Save the image digest, SBOM and vulnerability scan summary in the deployment log. A fixable critical/high finding blocks first deployment.

If transferring an image archive or using a registry, verify its digest against the Day 7 release evidence before loading or pulling. Registry login is required; do not publish the image to an unintended public namespace.

## 6. First start and readiness

```bash
docker compose -p memtrace-release -f compose.release.yaml up -d
docker compose -p memtrace-release -f compose.release.yaml ps
curl --fail --silent http://127.0.0.1:18070/api/v1/health
curl --fail --silent http://127.0.0.1:18070/api/v1/ready
curl --fail --silent http://127.0.0.1:18070/api/v2/system
```

Readiness must report the unique migration `007_day7_public_release`, release `0.1.0`, the frozen model, `provider_mode=real`, configured Key as a boolean only, and the frozen budgets. If migration, Provider, model or Key state differs, keep the proxy closed and stop.

Create the first one-use invitation only after readiness passes:

```bash
docker compose -p memtrace-release -f compose.release.yaml exec app \
  python -m memtrace_api.admin_cli invite-create --max-uses 1 --expires-hours 24
```

Transmit the one-time value through an approved secret channel. The deployment log records only invite ID, expiry and use count.

## 7. Reverse proxy and HTTPS

Expose only HTTPS publicly. The proxy must:

- redirect HTTP to HTTPS;
- preserve `Host` and the verified client/proxy boundary;
- proxy to `127.0.0.1:18070`;
- disable buffering and caching for `/api/v2/tasks/*/stream`;
- allow long-lived SSE connections with a timeout longer than the Provider timeout;
- enforce a request-body limit no larger than the application limit (1 MiB);
- set HSTS only after HTTPS is verified and rollback risk is understood;
- never log Cookie, CSRF token, request body, query text, response body or secrets.

Illustrative Nginx location settings (adapt to the actual installed proxy rather than copying blindly):

```nginx
client_max_body_size 1m;

location / {
    proxy_pass http://127.0.0.1:18070;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto https;
    proxy_buffering off;
}
```

Confirm the application CSP and other security headers survive the proxy. `PUBLIC_ORIGIN` must be the exact public HTTPS origin; do not use a wildcard.

## 8. Public smoke and isolation

Use two separate one-use invitations and two synthetic accounts. Verify:

1. register, store the one-time recovery code, logout and login;
2. one real streamed turn with actual model and usage;
3. background memory extraction, confirmation and later reuse;
4. memory-off and unrelated negative case;
5. second account cannot read the first account's task, memory, event or Pack ID (uniform 404);
6. restart preserves session, task, memory and quota;
7. browser console has no unexpected errors and network has no unexpected failures.

Do not reuse Day 7 browser credentials or test databases on the server.

## 9. Backup

Create a consistent backup from the running container into the dedicated backup volume:

```bash
stamp=$(date -u +%Y%m%dT%H%M%SZ)
docker compose -p memtrace-release -f compose.release.yaml exec app \
  python /app/ops/backup_sqlite.py \
  --source /app/data/memtrace.sqlite3 \
  --output "/app/backups/memtrace-${stamp}.sqlite3"
```

Record the emitted SHA-256, byte count, `quick_check=ok` and migration. Copy backups to encrypted off-host storage with access control. A backup is not accepted until a restore drill succeeds in a separate volume.

Recommended initial policy: daily backup, retain 7 daily and 4 weekly copies, then revise from actual usage/legal requirements. Account deletion is immediate in the primary database; ensure the published privacy notice explains backup retention and scheduled expiry.

## 10. Restore drill

Never overwrite the active database. Stop or isolate the target and restore into a new empty volume/file:

1. create a new Compose project/override that mounts a new data volume;
2. run `/app/ops/restore_sqlite.py` with the recorded hash and a non-existing destination;
3. start the isolated instance on a different loopback port;
4. verify `quick_check`, migration, health/ready, login and one complete synthetic golden path;
5. compare owner/task/memory/quota metadata counts without printing body data;
6. destroy only the isolated drill project after evidence is saved.

If the hash, quick check, migration or golden path fails, do not replace production. Preserve the failed drill logs without secrets and investigate.

## 11. Upgrade and rollback

Before any upgrade:

- make and verify a fresh backup;
- fetch the new immutable tag and verify its commit/digest;
- read the migration downgrade boundary;
- schedule a maintenance window if the migration can block SQLite writes.

For a code-only failure before irreversible writes, stop the new container and start the previous immutable image against a database version it supports. For a schema/data failure, restore the verified pre-upgrade backup into a new volume; do not casually run Alembic downgrade on live data.

Never move `v0.1.0`. A code fix is `v0.1.1` or later.

## 12. Incident checks

- Provider 401/403/model/credit failure: close new invitations, preserve metadata-only error codes, fix the official account/configuration; never enable Mock in production.
- Quota spike: inspect controlled quota/account metadata, revoke compromised sessions, rotate password/recovery credentials as appropriate.
- Suspected Key exposure: revoke at DeepSeek, replace the secret file, recreate the container and scan logs/artifacts; do not print the old or new value.
- Database corruption: stop writes, preserve the damaged volume, restore the latest verified backup into a new volume and document data-loss window.
- Privacy incident: disable affected account/session access, preserve metadata audit evidence, follow the project's retention/deletion notice and applicable reporting requirements.

## 13. Deployment evidence

The deployment report must include exact tag/SHA/image digest, host facts, Compose version, health/ready/system results, migration, synthetic account isolation, real usage, restart, backup/restore, SBOM/scan and log-canary results. It must exclude all secrets and user/model body content.
