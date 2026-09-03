# syntax=docker/dockerfile:1

FROM python:3.12

WORKDIR /SocketIO

COPY . .

RUN pip install --upgrade pip && \
    pip install -r requirements.txt

ENV ENVIRONMENT=production

CMD ["python", "app.py"]