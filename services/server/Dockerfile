# syntax=docker/dockerfile:1

FROM python:3.9

RUN apt-get update \
 && apt-get install -y sudo \
 && apt-get install -y nfs-common \
 && apt install -y texlive-latex-recommended \
 && apt-get install -y texlive-lang-french

WORKDIR /Server

COPY ./requirements.txt ./requirements.txt

RUN pip install -r requirements.txt \
  && pip uninstall -y PyCrypto PyMuPDF httplib2 \
  && pip install PyCryptodome PyMuPDF==1.24.8 httplib2==0.15.0

COPY . .

ENV ENVIRONMENT=production
ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "flask", "run", "--host=0.0.0.0"]
