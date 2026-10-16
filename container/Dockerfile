# TEMPLATE (Ops owner: verify with docker build). Build from the repo root:
#   docker build -f container/Dockerfile -t songdo-edge .
FROM ubuntu:24.04
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-yaml \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -m edge
WORKDIR /app
COPY --chown=edge:edge . /app
USER edge
ENV PYTHONPATH=/app/src
EXPOSE 8000
CMD ["python3", "-m", "edge.supervisor", "--config", "config/node.yaml"]
