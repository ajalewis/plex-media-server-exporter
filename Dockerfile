FROM python:3.12.0-alpine3.18

LABEL \
org.opencontainers.image.authors="alexanderashworthlewis@gmail.com" \
org.opencontainers.image.title="plex-media-server-exporter"

RUN mkdir /pms-exporter && \
  adduser -D -u 10000 -g exporter exporter && \
  chown -R exporter:exporter /pms-exporter

WORKDIR /pms-exporter

ENV PIP_ROOT_USER_ACTION=ignore

COPY requirements.txt main.py ./
COPY exporter exporter

RUN pip3 install --no-cache-dir -r requirements.txt

USER exporter:exporter

ENV METRICS_PORT=9299

EXPOSE ${PORT}

CMD [ "python3", "-m" , "main" ]