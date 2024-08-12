# syntax=docker/dockerfile:1

FROM python:3.12

RUN apt-get update \
 && apt-get install -y nfs-common poppler-utils \
 && pip install --upgrade pip

WORKDIR /Server

COPY ./requirements.txt ./requirements.txt

RUN pip install -r requirements.txt

COPY . .

ENV ENVIRONMENT=production
ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "flask", "run", "--host=0.0.0.0"]
