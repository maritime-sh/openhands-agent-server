# OpenHands agent server for Maritime

`ghcr.io/maritime-sh/openhands-agent-server` is the
[OpenHands agent server](https://github.com/OpenHands/software-agent-sdk)
packaged to run as a [Maritime](https://maritime.sh) agent: one Firecracker
micro-VM per sandbox, with an HTTPS and WebSocket URL, and sleep and wake with
memory kept.

It is the published `ghcr.io/openhands/agent-server:<version>-python` image
with one change: a launcher, [`maritime-start`](maritime-start), that binds the
agent server to `$PORT`. A Maritime VM routes its public URL to `$PORT` (18789
today), and the stock image listens on 8000. The launcher also makes
`localhost` resolve in the VM, and keeps state on Maritime's persistent volume
(`HOME=/data`).

Tags follow the upstream agent server: `:1.58.1` is built from
`ghcr.io/openhands/agent-server:1.58.1-python`. Recent releases are built every
six hours by [`publish.yml`](.github/workflows/publish.yml), after a smoke test.
`:latest` follows the newest release.

## Used by

- **OpenHands Agent Canvas**: Add Backend, then Providers, then Maritime.
  Canvas creates the agent and connects to it.
- **OpenHands Enterprise**: `RUNTIME=maritime`. The app server creates one
  agent per sandbox and claims it with `POST /api/init`.

## Run it yourself

```bash
curl -X POST https://api.maritime.sh/api/agents \
  -H "Authorization: Bearer $MARITIME_API_KEY" -H "Content-Type: application/json" \
  -d '{
    "name": "openhands",
    "framework": "custom",
    "imageName": "ghcr.io/maritime-sh/openhands-agent-server:latest",
    "exposedPort": 8080,
    "publicWeb": true,
    "memMb": 4096,
    "vcpus": 2,
    "initialEnvVars": [
      {"key": "OH_SESSION_API_KEYS_0", "value": "'"$(openssl rand -hex 32)"'", "isSecret": true},
      {"key": "OH_SECRET_KEY", "value": "'"$(openssl rand -hex 32)"'", "isSecret": true},
      {"key": "OH_ALLOW_CORS_ORIGINS_0", "value": "https://your-app.example.com", "isSecret": false}
    ]
  }'
```

When the agent is `active`, connect Agent Canvas to its `webUrl`
(`https://<agent-id>.mtm.sh`) with the `OH_SESSION_API_KEYS_0` value as the
API key. `publicWeb` lets the browser reach the URL; the session API key is
what protects the agent server. Set browser origins as `OH_ALLOW_CORS_ORIGINS_<n>`
at create: the agent server reads its CORS policy at boot, so origins sent later
on `POST /api/init` do not take effect. The API key needs the `provision`,
`deploy` and `manage` scopes (`manage` deletes agents).

## Environment

| Variable | Meaning |
| --- | --- |
| `PORT` | Port to bind. Maritime sets it; defaults to 8000 elsewhere. |
| `MARITIME_AGENT_SERVER_HOST` | Bind address. Defaults to `0.0.0.0`. |
| `OH_SESSION_API_KEYS_0`, `OH_SECRET_KEY`, `OH_DEFERRED_INIT`, ... | Read by the agent server as usual. |

## Test

```bash
docker build --platform linux/amd64 -t oh-maritime .
DOCKER_PLATFORM=linux/amd64 tests/smoke.sh oh-maritime
```

## License

MIT. The OpenHands agent server is MIT licensed by All Hands AI.
