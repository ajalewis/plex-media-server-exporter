FROM python:3.14.6-alpine3.24

LABEL \
org.opencontainers.image.authors="alexanderashworthlewis@gmail.com" \
org.opencontainers.image.title="plex-media-server-exporter"

RUN addgroup -g 10000 exporter && \
    adduser -D -H -u 10000 -G exporter exporter

WORKDIR /pms-exporter

ENV PIP_ROOT_USER_ACTION=ignore \
    PYTHONUNBUFFERED=1 \
    METRICS_PORT=9922

COPY requirements.txt ./

RUN pip3 install --no-cache-dir -r requirements.txt

COPY --chown=exporter:exporter requirements.txt main.py ./

COPY --chown=exporter:exporter exporter exporter

USER exporter:exporter

EXPOSE ${METRICS_PORT}

CMD [ "python3", "-m" , "main" ]