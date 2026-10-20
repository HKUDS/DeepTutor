# Optional request screening (fastapi-guard)

DeepTutor can screen HTTP requests inside the backend with [fastapi-guard](https://github.com/Guard-Core/fastapi-guard). It is **off by default**. When it is off, the package is never imported and the middleware stack is unchanged. Like any new setting, `system.json` gains the disabled `security_guard` block with its defaults on the next load, and a malformed block is replaced by the defaults.

The guard is an application-layer control. It complements a reverse proxy, WAF or firewall at the edge, and it keeps working when the backend port is reached without one (for example a published `:8001`, `deeptutor serve` on a LAN, or a tunnel).

## What it does

For every HTTP request it checks, in this order of concern:

- **IP lists**: an optional allowlist (only listed addresses pass) and an optional denylist.
- **Rate limit**: a sliding window per client address, 300 requests per 60 seconds by default.
- **Ban list**: an address that triggers repeated attack-pattern matches is blocked for a while.
- **Attack-pattern scan** of the URL path, query string and headers (XSS, SQL injection, path traversal and similar). A match returns `400`. The `ssrf` category is turned off because browsers send the page address as `Referer` and guard-core 4.4.0 flags localhost and LAN addresses in it, so SSRF patterns are not screened; this is to be revisited when the engine fix ships.

Rejected requests return `429` (rate limit) or `403` (IP lists, ban). The guard sits inside `CORSMiddleware`, so those responses still carry CORS headers and the browser shows the real status instead of an opaque CORS error.

## What it does not do

- It never reads request bodies. Prompts, documents and chat messages are free text, so body scanning is turned off (`detection_scan_body=False`).
- It does not screen WebSocket handshakes (`/ws`), only HTTP requests.
- It does not use Redis. Counters live in each backend process, so with `backend_workers` greater than 1 the effective limit is up to `rate_limit` times the worker count.
- It does not add security headers, handle CORS or send telemetry (`security_headers`, `enable_cors` and `enable_agent` are all off).

Two engine behaviours worth knowing, as of fastapi-guard 8.1.1 / guard-core 4.4.0 (later engine versions may change them): paths in the engine's default `exclude_paths` (`/docs`, `/redoc`, `/openapi.json`, `/openapi.yaml`, `/favicon.ico`, `/static`) skip the attack-pattern scan only, the rate limit and IP lists still apply to them; and an allowlisted address skips both the attack-pattern scan and the rate limit.

## Enable it

1. Install the extra (it adds `fastapi-guard`; `redis` is already a DeepTutor dependency, `maxminddb` and `cachetools` are new):

   ```bash
   pip install "deeptutor[guard]"      # or: pip install -r requirements/guard.txt
   ```

   In Docker set `DEEPTUTOR_EXTRAS: "guard"` on the service, the same way as other extras (see [CONTAINERIZATION.md](CONTAINERIZATION.md)).

2. Enable it in `data/user/settings/system.json`:

   ```json
   {
     "security_guard": {
       "enabled": true,
       "rate_limit": 300,
       "rate_limit_window": 60,
       "trusted_proxies": ["127.0.0.1", "::1"],
       "exempt_ips": ["127.0.0.1", "::1"],
       "whitelist": [],
       "blacklist": []
     }
   }
   ```

   Outside Docker the same keys can be set as process environment overrides: `DEEPTUTOR_GUARD_ENABLED`, `DEEPTUTOR_GUARD_RATE_LIMIT`, `DEEPTUTOR_GUARD_RATE_LIMIT_WINDOW`, `DEEPTUTOR_GUARD_TRUSTED_PROXIES`, `DEEPTUTOR_GUARD_EXEMPT_IPS`, `DEEPTUTOR_GUARD_WHITELIST` and `DEEPTUTOR_GUARD_BLACKLIST` (comma-separated IPs or CIDR ranges). The Docker entrypoint ignores process environment overrides, so in a container use `system.json`.

3. Restart the backend.

If `enabled` is true and `fastapi-guard` is not installed, the backend refuses to start and prints how to install it. Invalid IP or CIDR entries also fail at startup.

### Sizing the rate limit

The limit counts **every** HTTP request from one client address, including the frontend's background polling (several panels poll every 1 to 5 seconds). 300 per 60 seconds leaves room for a few open panels, whereas the 10 per 60 seconds that fastapi-guard 8.1.1 uses when nothing is configured would trip on normal use. The Next.js frontend serves its static assets itself, so those requests do not reach the backend and are not counted.

## Client address and proxies

The guard identifies a client by the socket peer of the request. It believes `X-Forwarded-For` only when the peer is listed in `trusted_proxies` (default: loopback only). A request from any other peer has its `X-Forwarded-For` ignored.

Uvicorn can also rewrite the peer from `X-Forwarded-For` (and from `FORWARDED_ALLOW_IPS`) before the application sees it, which would let a client choose its own identity. Every DeepTutor launch path already passes `proxy_headers=False` / `--no-proxy-headers` (`deeptutor/api/run_server.py`, `deeptutor_cli/main.py`, `deeptutor/runtime/launcher.py`, both `Dockerfile` launch lines), so the guard sees the real peer. `tests/api/test_security_guard.py` checks this through `uvicorn.Config(...).load()`.

If you start the backend yourself, keep the flag:

```bash
python -m uvicorn deeptutor.api.main:app --host 0.0.0.0 --port 8001 --no-proxy-headers
```

If a reverse proxy sits in front of the backend, add its address to `trusted_proxies`; otherwise every client looks like the proxy. The guard warns when it bans a private address because of this.

Dual-stack binds: with guard-core 4.4.0, a peer reported in IPv4-mapped form (`::ffff:a.b.c.d`, as on a dual-stack `::` bind) is not matched against IPv4 `trusted_proxies` entries, so a reverse proxy's `X-Forwarded-For` is ignored and all its clients share the proxy's bucket. The default launch paths bind `0.0.0.0` and are not affected. If you bind `::`, also list the mapped form of each proxy, for example `["10.0.0.0/8", "::ffff:10.0.0.0/104"]` (checked with guard-core 4.4.0, and covered by a test). Later guard-core versions may not need this.

**Bundled frontend.** The Next.js proxy (`web/proxy.ts`) deletes `X-Forwarded-For` and the other forwarded headers from browser requests (`web/lib/backend-forward.ts`) and does not add the browser's address. Requests that reach the backend through it all arrive from the frontend's own address (loopback in the default layout), with no forwarded header. One shared limit would throttle every user together, so `exempt_ips` (default `127.0.0.1` and `::1`) exempts that address from the rate limit. Through the frontend, requests are therefore screened for attack patterns and the denylist, but not rate-limited. Per-client limits apply to requests that reach the backend directly, or through a reverse proxy that sets `X-Forwarded-For` and is listed in `trusted_proxies` (with `exempt_ips` containing loopback, a loopback request that carries `X-Forwarded-For` is limited as the forwarded client). `exempt_ips` skips the rate limit only: the denylist, bans and the attack-pattern scan still apply to listed addresses. The guard does not ban loopback addresses.

**Allowlist with the bundled frontend.** If `whitelist` is set, frontend traffic (loopback) is refused unless loopback is listed. With the bundled frontend, add `127.0.0.1` and `::1` to `whitelist`. The allowlist and denylist then govern direct backend access only, because the frontend hides browser addresses.
