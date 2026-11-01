# syntax=docker/dockerfile:1
# Check Point security-ops agent. Multi-stage: wheels are built in a throwaway
# stage, the runtime is python:3.12-slim running as an unprivileged user with a
# read-only root filesystem (the chart mounts an emptyDir on /tmp).
ARG BASE_IMAGE=public.ecr.aws/docker/library/python:3.12-slim

FROM ${BASE_IMAGE} AS build
WORKDIR /src
COPY requirements.txt .
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt

FROM ${BASE_IMAGE}
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HOME=/tmp PORT=8080
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin agent
WORKDIR /app
COPY --from=build /wheels /wheels
RUN pip install --no-cache-dir --no-index /wheels/* && rm -rf /wheels
COPY chkp_agent /app/chkp_agent
USER 10001
EXPOSE 8080
ENTRYPOINT ["python", "-m", "chkp_agent.app"]
