# syntax=docker/dockerfile:1

FROM python:3.12

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y poppler-utils \
    && apt install -y texlive-latex-recommended \
    && apt-get install -y texlive-lang-french\
    && apt-get install -y libhdf5-dev \
    && pip install --upgrade pip

WORKDIR /Executor

COPY ./requirements.txt ./requirements.txt

RUN pip install -r requirements.txt

COPY . .

ENV ENVIRONMENT=production

CMD ["python3", "-m", "job_executor"]
