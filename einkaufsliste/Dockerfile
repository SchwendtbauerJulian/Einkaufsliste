# Basis-Image kommt normalerweise von Home Assistant (build.yaml).
# Fehlt es, wird ein schlankes Python-Image genommen – die App braucht nur Python.
ARG BUILD_FROM=python:3.13-alpine
FROM ${BUILD_FROM}

RUN command -v python3 > /dev/null || apk add --no-cache python3

COPY integration /integration
COPY server.py /server.py

CMD ["python3", "-u", "/server.py"]
