"""End-to-end check of the image on real Maritime, as both OpenHands
integrations use it.

Creates one agent from the image, then checks, through the agent's public URL:
  1. the micro-VM boots and the agent server answers on $PORT (dormant),
  2. POST /api/init claims it with the init key (the enterprise flow),
  3. /api is closed without the session key and open with it,
  4. a WebSocket upgrade reaches the agent server (bash events stream),
  5. sleep and wake keep the claimed server (memory snapshot),
and deletes the agent at the end, whatever happened.

    MARITIME_API_KEY=mk_... python tests/live.py [image]

Needs httpx and websockets. Costs one agent for a few minutes.
"""

import asyncio
import json
import os
import secrets
import sys
import time

import httpx
import websockets

API = os.environ.get('MARITIME_API_URL', 'https://api.maritime.sh').rstrip('/')
KEY = os.environ['MARITIME_API_KEY']
IMAGE = sys.argv[1] if len(sys.argv) > 1 else 'ghcr.io/maritime-sh/openhands-agent-server:latest'
HEADERS = {'Authorization': f'Bearer {KEY}'}
ORIGIN = 'https://app.example.com'


def step(message: str) -> None:
    print(f'[{time.strftime("%H:%M:%S")}] {message}', flush=True)


async def wait_status(client: httpx.AsyncClient, agent_id: str, want: str, timeout: int = 900) -> dict:
    deadline = time.monotonic() + timeout
    while True:
        agent = (await client.get(f'{API}/api/agents/{agent_id}', headers=HEADERS)).raise_for_status().json()
        if agent['status'] == want:
            return agent
        if agent['status'] == 'error':
            raise RuntimeError(f'agent went to error: {agent}')
        if time.monotonic() > deadline:
            raise TimeoutError(f'agent stuck in {agent["status"]}')
        await asyncio.sleep(3)


async def wait_init_state(client: httpx.AsyncClient, url: str, timeout: int = 600) -> str:
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            response = await client.get(f'{url}/api/init')
            last = f'{response.status_code} {response.text[:120]}'
            if response.status_code == 200:
                return response.json()['state']
        except httpx.HTTPError as exc:
            last = repr(exc)
        await asyncio.sleep(3)
    raise TimeoutError(f'/api/init never answered 200; last: {last}')


async def main() -> int:
    key = secrets.token_urlsafe(32)
    agent_id = None
    async with httpx.AsyncClient(timeout=120) as client:
        try:
            step(f'create agent from {IMAGE}')
            agent = (
                await client.post(
                    f'{API}/api/agents',
                    headers=HEADERS,
                    json={
                        'name': f'openhands-live-{secrets.token_hex(3)}',
                        'externalId': 'openhands:live-test',
                        'framework': 'custom',
                        'imageName': IMAGE,
                        'exposedPort': 8080,
                        'publicWeb': True,
                        'healthCheckPath': '/alive',
                        'memMb': 4096,
                        'vcpus': 2,
                        'idleTtlSeconds': 3600,
                        'initialEnvVars': [
                            {'key': 'OH_DEFERRED_INIT', 'value': '1', 'isSecret': False},
                            {'key': 'OH_SECRET_KEY', 'value': key, 'isSecret': True},
                            # The agent server reads its CORS policy at boot.
                            {'key': 'OH_ALLOW_CORS_ORIGINS_0', 'value': ORIGIN, 'isSecret': False},
                        ],
                    },
                )
            ).raise_for_status().json()
            agent_id = agent['id']
            step(f'agent {agent_id} status={agent["status"]} webUrl={agent.get("webUrl")}')

            agent = await wait_status(client, agent_id, 'active')
            url = agent['webUrl'].rstrip('/')
            step(f'active; waiting for the agent server at {url}')

            state = await wait_init_state(client, url)
            assert state == 'dormant', f'expected dormant, got {state}'
            step('1. dormant agent server answers through the public URL: OK')

            response = await client.post(
                f'{url}/api/init',
                headers={'X-Init-API-Key': key},
                json={
                    'session_api_keys': [key],
                    'secret_key': key,
                    'conversations_path': '/workspace/conversations',
                    'bash_events_dir': '/workspace/bash_events',
                    'conversation_worktree_root': '/workspace/worktrees',
                    'env': {},
                    'allow_cors_origins': [ORIGIN],
                },
            )
            assert response.status_code == 200, f'init: {response.status_code} {response.text}'
            step('2. POST /api/init claimed it: OK')

            closed = await client.get(f'{url}/api/conversations/search')
            opened = await client.get(
                f'{url}/api/conversations/search', headers={'X-Session-API-Key': key}
            )
            assert closed.status_code == 401, f'no key: {closed.status_code}'
            assert opened.status_code == 200, f'key: {opened.status_code} {opened.text[:200]}'
            step('3. /api closed without the key, open with it: OK')

            preflight = await client.options(
                f'{url}/api/conversations/search',
                headers={
                    'Origin': 'https://app.example.com',
                    'Access-Control-Request-Method': 'GET',
                    'Access-Control-Request-Headers': 'x-session-api-key',
                },
            )
            allow = preflight.headers.get('access-control-allow-origin')
            assert preflight.status_code == 200 and allow == ORIGIN, (
                f'preflight: {preflight.status_code} allow-origin={allow}'
            )
            step('   CORS preflight from the app origin: OK')

            ws_url = url.replace('https://', 'wss://') + f'/sockets/bash-events?session_api_key={key}'
            async with websockets.connect(ws_url, open_timeout=30) as ws:
                await ws.ping()
                step(f'4. WebSocket upgrade reached the agent server ({ws_url.split("?")[0]}): OK')

            step('sleep the agent')
            (await client.post(f'{API}/api/agents/{agent_id}/sleep', headers=HEADERS)).raise_for_status()
            await wait_status(client, agent_id, 'sleeping', timeout=300)
            step('asleep; waking it with a request to its URL')
            state = await wait_init_state(client, url, timeout=300)
            assert state == 'ready', f'expected ready after wake, got {state}'
            again = await client.get(
                f'{url}/api/conversations/search', headers={'X-Session-API-Key': key}
            )
            assert again.status_code == 200, f'after wake: {again.status_code}'
            step('5. woke on request, still claimed, key still valid: OK')
            print(json.dumps({'result': 'PASS', 'agent_id': agent_id, 'image': IMAGE}))
            return 0
        finally:
            if agent_id:
                response = await client.delete(f'{API}/api/agents/{agent_id}', headers=HEADERS)
                step(f'delete agent {agent_id}: {response.status_code}')
                if response.status_code not in (200, 204):
                    print('FAIL: delete needs a key with the manage scope', flush=True)
                    sys.exit(1)


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
