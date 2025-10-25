# syntax=docker/dockerfile:1

FROM python:3.12

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y poppler-utils libhdf5-dev texlive-latex-base texlive-latex-recommended \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --upgrade pip setuptools wheel

WORKDIR /Executor

COPY ./requirements.txt ./requirements.txt

RUN pip install -r requirements.txt

COPY . .

ENV ENVIRONMENT=production

CMD ["python3", "-m", "job_executor"]