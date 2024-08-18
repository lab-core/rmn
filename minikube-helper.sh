#!/bin/bash

function printBashUsage {
  echo "This script helps managing minikube and k8s."
  echo "Usage:"
  echo "-h | --help: display this message"
  echo "-i | --install: install all the configurations."
  echo "-a | --apply: apply the yml files."
  echo "-r | --rollout: rollout deployments."
  echo "-d | --deployment: deployment name for rollout. Default: all deployments will be rollout."
  echo "-s | --start: start minikube."
  echo "-m | --memory: memory in MB for minikube. Default: 24576."
  echo "-c | --cpus: cpus for minikube. Default: 3."
  echo "-n | --nohup: run minikube start with nohup."
  echo "-j | --cron-job: create service account for the cron jobs."
}

# load config arguments in one line
A=()
while [ ! -z "$1" ]; do
    for v in "$1"; do
        A+=("$v")
    done
    shift 1;
done

# parse arguments
MEMORY="12268"
CPUS="3"
i=0

if [ -z ${A[${i}]} ]; then
  printBashUsage
  exit 0
fi

while [ ! -z ${A[${i}]} ]; do
  case ${A[${i}]} in
    -h|--help) printBashUsage; exit 0;;
    -i | --install) INSTALL="1"; ((i+=1));;
    -a | --apply) APPLY="1"; ((i+=1));;
    -r | --rollout) ROLLOUT="1"; ((i+=1));;
    -d | --deployment) DEPLOYMENT=${A[((i+1))]}; ((i+=2));;
    -s | --start) START="1"; ((i+=1));;
    -m | --memory) MEMORY=${A[((i+1))]}; ((i+=2));;
    -c | --cpus) CPUS=${A[((i+1))]}; ((i+=2));;
    -n | --nohup) NOHUP="1"; ((i+=1));;
    -j | --cron-job) CRON="1"; ((i+=1));;
    *) echo "Argument ${A[${i}]} not recognized."; echo ""; printBashUsage; exit 1;;
  esac
done

if [[ ! -z $START ]]; then
  CMD="minikube start --vm-driver=docker --memory=${MEMORY} --cpus=${CPUS}"
  echo "$CMD"
  if [[ ! -z $NOHUP ]]; then
    nohup $CMD &
  else
    exec $CMD &
  fi
  exit 0
fi

if [[ ! -z $INSTALL ]]; then
  minikube addons enable ingress
  kubectl apply -f https://github.com/kedacore/keda/releases/download/v2.9.3/keda-2.9.3.yaml
  echo "Run the following commands:
        minikube ssh
        sudo mkdir -p /data/nfs /data/mongo && exit
        ./minikube-helper.sh -a"
  exit 0;
fi

if [[ ! -z $APPLY ]]; then
  SCRIPT_DIR=$(cd $(dirname "${BASH_SOURCE[0]}") && pwd)
  kubectl apply -f ${SCRIPT_DIR}/deployment
  kubectl get pods
fi

if [[ ! -z $ROLLOUT ]]; then
  if [[ -z $DEPLOYMENT ]]; then
    kubectl rollout restart deployment/server
    kubectl rollout restart deployment/socketio
    kubectl rollout restart deployment/webapp
    # kubectl rollout restart ingress-nginx/ingress-nginx-controller
  else
    kubectl rollout restart deployment/$1
  fi
  kubectl get pods
fi

if [[ ! -z $CRON ]]; then
  kubectl create sa cron
  kubectl create clusterrolebinding cron --clusterrole edit --serviceaccount=default:cron
fi

exit 0
