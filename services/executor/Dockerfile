# syntax=docker/dockerfile:1

FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y python3-pip \
    && apt-get install -y poppler-utils \
    && apt-get install -y build-essential \
    && apt-get install -y python3-dev \
    && apt-get install -y python3-opencv \
    && pip3 install --upgrade pip

WORKDIR /Executor

COPY ./requirements.txt ./requirements.txt

RUN pip3 install -r requirements.txt

RUN pip uninstall -y PyCrypto && pip install PyCryptodome

COPY . .

ENV ENVIRONMENT=production

CMD ["python3", "-m", "job_executor"]
