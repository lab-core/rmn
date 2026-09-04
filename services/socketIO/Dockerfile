# syntax=docker/dockerfile:1

FROM python:3.14

WORKDIR /SocketIO

COPY . .

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Unprivileged runtime user. socketIO writes nothing to disk, so the app
# directory can stay root-owned and read-only.
RUN groupadd --gid 1000 rmn \
    && useradd --uid 1000 --gid rmn --create-home --shell /usr/sbin/nologin rmn

ENV ENVIRONMENT=production
ENV HOME=/home/rmn

USER rmn

CMD ["python", "app.py"]
