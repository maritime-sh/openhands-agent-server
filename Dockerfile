# The OpenHands agent server, ready to run as a Maritime agent.
#
# Same image as ghcr.io/openhands/agent-server, with a launcher that binds the
# port Maritime routes to ($PORT). See maritime-start for why.
ARG AGENT_SERVER_TAG=1.58.1-python
FROM ghcr.io/openhands/agent-server:${AGENT_SERVER_TAG}

ARG AGENT_SERVER_TAG
LABEL org.opencontainers.image.source="https://github.com/maritime-sh/openhands-agent-server" \
      org.opencontainers.image.description="OpenHands agent server for Maritime micro-VMs (based on ghcr.io/openhands/agent-server:${AGENT_SERVER_TAG})" \
      org.opencontainers.image.licenses="MIT"

COPY --chmod=0755 maritime-start /usr/local/bin/maritime-start

ENTRYPOINT ["tini", "--", "/usr/local/bin/maritime-start"]
