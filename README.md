# Reconaissance des matricules et notes

### Minimum configuration

To use the webapp, you need one of the following versions at minimum for your browser:
- Chrome 119
- Edge 119
- Firefox 121
- Safari 17.4

### User guide

- Add a front page to your copy, if necessary, to grade them
- Define a template to mark the zone where to search the grades and matricules (if necessary). If searching matricules, the app will also automatically search for the matricule on the top right corner of all pages except the front page.
- Start a new correction. A template can have more grade boxes than the exam has questions: check "Ignorer" for the unused questions (0 page, 0 point). They are skipped everywhere and their box is left blank on the front page. If a column matching the regex '(?i)(gr|groupe?s?)$' is found, the corresponding content will be used to separate the copies into sub directories. The csv file must include a 'matricule' column as well as a 'Nom complet' column. Using a moodle csv file works immediately (you should fix the maximum grade).
- Then validate grades and matricules if necessary (it's not necessary if using directly moodle zip file or if each file contain it in its name).
- Then finalize and download the resulting cvs file, all the copies renamed and split into groups (if provided), and the zip files to upload to moodle (as well as the csv file).

### General information for installation

##### Nginx
You should deploy an nginx reverse proxy to point to the kubernetes server. You may adapt the nginx.conf file for this purpose (especially, enter your own certificate and set your server name).

##### Mongo
Mongo is run within the kubernetes cluster now.

##### Firebase
Firebase has been removed and a NFS (run inside the cluster) is instead used to synchronize and share files between containers, as well as persistent storage.

## Docker builds

The Dockerfiles copy and install the dependencies before the source, so a code
change only rebuilds the last `COPY` layer, and the pip/npm download caches are
kept between builds (`RUN --mount=type=cache`, BuildKit). CI publishes a layer
cache next to each image (`rmni/<service>:buildcache`) and `docker-compose.yml`
points `cache_from` at it, so a local build downloads the apt/pip/npm layers
instead of rebuilding them:
```
docker compose build   # pulls the cached layers, builds only your code
```
To run the published images without building, replace `build:` with
`image: rmni/<service>:main` for that service.

## Minikube
You can use the ```minikube-helper.sh``` script. Otherwise, you have more details below.

To start minikube with 2 cpus and 10G of memory:
```
minikube start --vm-driver=docker --memory=10986 --cpus=2
```

The folder used on the host path by the Mongo database and the NFS needs to be creted the first time:
```
minikube ssh
sudo mkdir -p /data/nfs /data/mongo
```

#### Ingress
nginx is only used as a reverse proxy to redirect all requests to kubernetes and to handle certificates.
All the routing part is handle by ingress (i.e., nginx in kubernetes). Ingress needs to be enabled in minikube:
```
minikube addons enable ingress
```

#### KEDA update
Use the newest KEDA whose tested window includes the cluster's Kubernetes
version (see the [compatibility matrix](https://keda.sh/docs/latest/operate/cluster/#kubernetes-compatibility)):
KEDA 2.12 (latest patch: 2.12.1, used below) covers Kubernetes 1.26 - 1.28.
`--server-side` is required because the ScaledJob CRD is too large for a
client-side apply.
```
kubectl apply --server-side -f https://github.com/kedacore/keda/releases/download/v2.12.1/keda-2.12.1.yaml
kubectl get pods -n keda        # operator, metrics-apiserver and admission-webhooks Running
kubectl get scaledjob            # job-executor READY/ACTIVE True
```
Upgrading in place from KEDA 2.9 needs two extra steps, otherwise the apply
stops half-way (admission webhook created, operator and metrics server left on
the old version, `kubectl` printing `the server is currently unable to handle
the request` for `external.metrics.k8s.io`):

- the `keda-metrics-apiserver` Service renamed its ports (2.9: `metrics:9022`,
  2.12: `metrics:8080`); a server-side apply merges both lists and fails with
  `spec.ports[3].name: Duplicate value: "metrics"`. Delete the Service first,
  the apply recreates it immediately;
- the Deployments were created by a client-side apply and still own their
  `resources`/`env` fields: add `--force-conflicts` (the two
  `failed to migrate ... last-applied-configuration` warnings are harmless).
```
kubectl delete svc -n keda keda-metrics-apiserver
kubectl apply --server-side --force-conflicts -f https://github.com/kedacore/keda/releases/download/v2.12.1/keda-2.12.1.yaml
```
Since the node pulls images slowly, pre-pull the three
`ghcr.io/kedacore/*:2.12.1` images with `minikube ssh -- docker pull ...` first
so the operator is not down for long: no executor Job is started while it
restarts.

Do not stay on KEDA < 2.10.1 with a recent kubectl: its metrics server answers
the discovery of `external.metrics.k8s.io/v1beta1` with an empty list when no
ScaledObject exists (a ScaledJob is not enough), and every kubectl command prints
`couldn't get resource list for external.metrics.k8s.io/v1beta1: Got empty
response`. Fixed upstream and shipped from KEDA 2.10.1. KEDA < 2.10 also never
resets a ScaledJob's `Ready` condition to True after a transient failure.

#### Secrets
All service credentials live in a single Kubernetes Secret named `rmn-secrets`
(MongoDB user/password, the Redis password, the `/admin/*` `ADMIN_API_KEY`, and
the Slack token). The manifests reference it with `secretKeyRef`; no credential
is committed. Create it **before** deploying:
```
kubectl create secret generic rmn-secrets \
  --from-literal=mongodb-user=adminuser \
  --from-literal=mongodb-password="$(openssl rand -hex 24)" \
  --from-literal=redis-password="$(openssl rand -hex 24)" \
  --from-literal=admin-api-key="$(openssl rand -hex 32)" \
  --from-literal=slack-token=""     # xoxb-... or empty to disable health-check pings
```
(Or copy `deployment/secrets.example.yml` to `deployment/secrets.yml`, fill it
in, and `kubectl apply -f deployment/secrets.yml` — that file is gitignored.)

The same file can be generated instead of hand-edited:
```
scripts/generate-secrets.sh                  # fresh random values, slack-token empty
scripts/generate-secrets.sh --from-env .env  # reuse the docker-compose credentials
scripts/generate-secrets.sh --slack-token xoxb-...
kubectl apply -f deployment/secrets.yml
```
It never overwrites an existing `secrets.yml`: move the old file away first if
you want a new one (the Mongo root password cannot be changed by rewriting the
Secret alone).
The KEDA redis scaler authenticates via the `redis-trigger-auth`
`TriggerAuthentication` in `deployment/executor.yml`, which reads the same
`redis-password`. On an existing Mongo volume the root password is fixed at
first init; to change it, rotate inside mongo (`db.changeUserPassword`) then
update the Secret.

#### Deploy all services
`deployment/kustomization.yaml` lists every manifest (it leaves out
`secrets.example.yml` so the placeholder credentials are never installed).
Once `rmn-secrets` exists, deploy the whole stack from the repository root:
```
kubectl apply -k deployment/
```
To preview the rendered manifests without applying them: `kubectl kustomize deployment/`.

#### Public hostname
The site hostname is defined once, in the `rmn-config` ConfigMap generated by
`deployment/kustomization.yaml` (`host=rmn.mgi.polymtl.ca`). Kustomize copies it
into both Ingress rules (`deployment/replacements.yaml`) and the socketIO
Deployment reads it for its CORS allow-list. To deploy against another host
(staging, minikube) without editing any file:
```
scripts/deploy.sh rmn.example.org            # apply
scripts/deploy.sh rmn.example.org --dry-run  # only print the manifests
```

#### Rotating the Slack token
The Slack token was committed to git history, so it must be regenerated in the
Slack app settings (revoking the old one) — that is the actual fix. Then update
the cluster Secret and roll the server with the helper:
```
scripts/rotate-slack-token.sh <new-xoxb-token>
```
It patches `rmn-secrets`, `kubectl rollout restart deployment/server`, and — if a
local `.env` is present — updates `SLACK_TOKEN` there too. To purge the old token
from history entirely, use `git filter-repo` (separate, history-rewriting step).

#### Modify deployment
Once a deployment yml file has been modified, re-apply the kustomization (applying
a single file with `-f` skips the host replacement, so `ingress.yml` would be
deployed with its `RMN_HOST` placeholder):
```
kubectl apply -k deployment/
```
Then, to ensure the new pods are created, rollout the service for a deployment:
```
kubectl rollout restart deployment <modified deployment>
```
Or delete the corresponding pods for a Replication Controller:
```
kubectl delete pods <modified deployment pod>
```

#### Cluster sentinel (health checks)
`deployment/k8s-health.sh` (also `scripts/k8s-health.sh`) inspects the cluster
with `kubectl` and reports anything unhealthy: API readiness, node
Ready/pressure, pods (Pending too long, CrashLoopBackOff, image pull errors,
containers not ready, restart count, OOMKilled, failed job pods), Deployments and
ReplicationControllers missing replicas, failed executor Jobs, CronJobs without
a recent success, KEDA ScaledJob readiness, PVC/PV not Bound, recent Warning
events and HTTP probes of the public host (`/`, `/api/`, `/socket.io/`).
Exit code: 0 healthy, 1 warnings, 2 critical, 3 API unreachable.
```
scripts/k8s-health.sh                       # full report
scripts/k8s-health.sh -q --host rmn.mgi.polymtl.ca   # silent when healthy
scripts/k8s-health.sh --help                # thresholds, Slack options
```
The `health-sentinel` CronJob (`deployment/health-sentinel.yml`, part of the
kustomization) runs it in-cluster every 15 minutes under a read-only service
account and posts to Slack (`rmn-config.slack-channel`, token from
`rmn-secrets.slack-token`) **only when the set of issues changes**, plus one
"recovered" message when they clear; the last state lives in the
`health-sentinel-state` ConfigMap. A run that is stuck is killed after 10 min.
Check it with `kubectl get cronjob health-sentinel` and
`kubectl logs job/<health-sentinel-...>`.

The CronJob runs with `--exit-zero`: a run that finds issues still completes
successfully (the findings go to Slack and the job log), so a sentinel pod in
`Error` means the script itself could not run (API unreachable, crash, killed
by the 10 min deadline). Without that flag the sentinel's own failed Jobs would
trip its "jobs failed in the last 24h" and "cronjob without a recent success"
checks and keep the warning alive after the real issue was fixed. When
upgrading from a version without the flag, delete the old failed sentinel jobs
so they stop showing up for 24 h:
```
kubectl get jobs -o name | grep health-sentinel | while read -r j; do kubectl delete "$j"; done
```

#### NFS server hardening
The in-cluster NFS server must run privileged, so `deployment/nfs.yml` limits its
blast radius: the image is pinned by digest, the Service is `ClusterIP` only (no
NodePort), a `NetworkPolicy` allows only TCP/2049 from the node network and no
egress at all, and the pod refuses to share a node with any other pod labelled
`rmn.polymtl.ca/privileged=true` (label your other privileged workloads that
way). Two things to set up per cluster:

- `node-cidr` in `deployment/kustomization.yaml` **must** be your node network
  (`kubectl get nodes -o wide`); the kubelet mounts NFS from the node, so this is
  the only legitimate source. The default is minikube's `192.168.49.0/24`.
- The policy is enforced only by a CNI with NetworkPolicy support (see
  "NetworkPolicy needs a CNI that enforces it" below).
- Optional: label a dedicated node `rmn.polymtl.ca/nfs-node=true`; the pod
  prefers it. Turn the preference into a requirement (and taint the node) once
  you have such a node.

##### NetworkPolicy needs a CNI that enforces it
The CNI (Container Network Interface) plugin is what gives pods their network.
Kubernetes only *stores* `NetworkPolicy` objects; enforcing them is the CNI's
job, and only some plugins do it (calico, cilium, ...). A cluster without one
accepts the object and silently ignores it. To check yours:
```
kubectl get pods -n kube-system -o name | grep -iE 'calico|cilium|kindnet|flannel|weave'
```
No match means no policy engine. **This is the case of the production minikube**
(docker driver, only `kube-proxy` in `kube-system`, checked 2026-09-04): the
`nfs-server` policy is a no-op there, so any pod can still reach the NFS server
on any port and the NFS pod can open outbound connections. The other NFS
measures (ClusterIP only, digest-pinned image, node isolation) do apply, so this
is an accepted residual risk, not a broken deployment.

Do not switch the CNI on a running single-node minikube: it is disruptive and
easy to get wrong. Fix it when the cluster is recreated, ideally together with
the Kubernetes upgrade (1.26 is out of support): `minikube start --cni=calico`
then `kubectl apply -k deployment/`, and verify enforcement once with
`kubectl exec deploy/server -- sh -c 'timeout 3 nc -zv <nfs-ip> 111 || echo blocked'`
(port 111 must be blocked, 2049 from the node still works).

##### The NFS service IP (`nfs-ip`)
The kubelet mounts NFS volumes from the node and does not use cluster DNS, so
`server.yml` / `executor.yml` must give the NFS server as an **IP**, not as the
`nfs` Service name. `deployment/kustomization.yaml` therefore pins the Service's
`clusterIP` and injects the same value into both mounts (`nfs-ip`, default
`10.105.99.184`). It is an arbitrary address you choose, with two constraints:

- inside the cluster's service range: `kubectl get pod -n kube-system -l
  component=kube-apiserver -o jsonpath='{.items[0].spec.containers[0].command}'
  | tr , '\n' | grep service-cluster-ip-range` (minikube: `10.96.0.0/12`);
- not already taken: `kubectl get svc -A -o custom-columns=NS:.metadata.namespace,NAME:.metadata.name,IP:.spec.clusterIP`.

On an existing cluster keep the value the `nfs` Service already has
(`kubectl get svc nfs -o jsonpath='{.spec.clusterIP}'`): a Service's clusterIP
is immutable, so changing it means deleting and recreating the Service, and
every pod mounting the old address must be rolled.

#### Non-root containers
No application container runs as root. The `server`, `executor` and `socketio`
images create a `rmn` user (UID/GID 1000) and switch to it; the webapp uses
`nginxinc/nginx-unprivileged` (nginx user, port 8080 behind a Service on 80).
The Deployments pin this with `runAsNonRoot`, `runAsUser: 1000`, no privilege
escalation and all capabilities dropped. Only the NFS server (privileged by
necessity, see above) is exempt.

`server` and `executor` share UID 1000 because they read and write the same NFS
share, and Kubernetes does not apply `fsGroup` to NFS volumes. **When upgrading a
cluster whose share was written by the old root-running images, chown it once
before rolling the new images**, otherwise they cannot overwrite or delete the
existing files:
```
kubectl exec rc/nfs -- chown -R 1000:1000 /mnt/nfs_share
```
The same applies to files copied onto the share by hand.

#### Hardening defaults
- **Login tokens expire** after `TOKEN_TTL_DAYS` (default 30) days. The server
  creates a Mongo TTL index on `tokens.creation_time` at start-up and, like the
  socketIO server, also rejects any token older than the TTL (tokens without a
  timestamp count as expired). Set the variable on both `server` and `socketio`
  to change it; `0` disables expiry. `/admin/delete/tokens` still works for a
  forced logout.
- **Request bodies are capped** at `MAX_UPLOAD_GB` (default 5, matching the
  Ingress `proxy-body-size`); larger uploads get a JSON 413. Uploads stream to
  the share in one copy, and the gunicorn worker timeout (`GUNICORN_CMD_ARGS`,
  1800 s) and the Ingress `proxy-read-timeout` are sized for a 5 GB upload.
  Note the node needs about twice the upload size free on disk while a request
  is in flight (ingress buffer + the multipart spool file).
- **Security headers** come from the front nginx (`security_headers`, including
  the nonce-based CSP); the webapp image and the Flask API add the safe subset
  themselves so they hold without it.
- **Services are `ClusterIP`**: `server`, `socketio` and `webapp` are only
  reachable through the Ingress (they used to be `NodePort`, i.e. exposed on the
  node's external interface, bypassing the login rate limit).
- **Resource requests/limits** are set on every workload (memory limits only,
  no CPU throttling). The executor's `MAX_RAM_GB` must stay below its memory
  limit in `executor.yml`.
- **Dependencies**: `.github/dependabot.yml` opens weekly update PRs (pip, npm,
  Dockerfiles, docker-compose, actions); the `dependency-audit` workflow posts a
  pip-audit / npm audit report on PRs touching a manifest and every Monday.

#### Persistent volume: NFS server
WARNING: you need to mount a persistent volume that correspond to the path given to the nfs server, otherwise you will have an error as docker is not able to mount other paths for a nsf server. Furthermore, if using minikube, the path of the persistent volume needs also to be persistent in minikube: you can use a default persistent path like "/data" or any other path that has been mounted in minikube to communicate with the host.

Access to nsf pods from outside
```
kubectl port-forward <nfs pod> :2049
```

You will have an output like this one:
```
Forwarding from 127.0.0.1:42349 -> 2049
Forwarding from [::1]:42349 -> 2049
```

Then, mount the nfs volume:
```
sudo mount -t nfs -o port=42349 127.0.0.1:/ /your/host/path/folder
```

To mount a volume into minikube, open a port (here 35475) for 192.168.49.2 (minikube ip) with:
```
sudo ufw allow from 192.168.49.2 to any port 35475
```
Then, mount the volume into minikube:
```
minikube mount --port=35475 ./k8s_storage:/mnt/k8s_storage
```

#### Cron job
The nfs connection may hang from time to time. To avoid this issue, we rollout the server pod every day with a cron job that will patch the server by modifying the date and trigger a rollout. `deployment/daily-rollout.yml` (part of `kubectl apply -k deployment/`) carries the CronJob, the `cron` ServiceAccount and a Role that only allows patching the `server` Deployment. Older clusters bound that ServiceAccount to the cluster-wide `edit` role by hand; drop that binding once the manifest is applied:
```
kubectl apply -f deployment/daily-rollout.yml
kubectl delete clusterrolebinding cron --ignore-not-found
```

### Admin commands

They need to be run locally on the server (depending on nginx/ingress configuration).

Every `/admin/*` endpoint requires the shared operator secret `ADMIN_API_KEY`,
passed in the `X-Admin-Key` request header. Set the secret in the server
environment first; if it is unset the admin endpoints are disabled (fail closed).
(An `admin_key` form field or `?admin_key=...` query string is also accepted as a
fallback, but prefer the header: query-string and form secrets tend to be
captured in access logs, browser history and Referer headers.)

```
# docker compose: ADMIN_API_KEY comes from the gitignored .env next to
# docker-compose.yml (see "Secrets"); export it in your shell from there.
export ADMIN_API_KEY=$(grep '^ADMIN_API_KEY=' .env | cut -d= -f2-)

# kubernetes: the server reads rmn-secrets/admin-api-key (see "Secrets");
# export the same value in the shell you run the commands from.
export ADMIN_API_KEY=$(kubectl get secret rmn-secrets -o jsonpath="{.data['admin-api-key']}" | base64 -d)
```

In the examples below, `$ADMIN_API_KEY` is the value exported above.
`./minikube-helper.sh -r` does this itself before creating an executor pod.
(A standalone `admin-api-key` Secret from older versions is no longer read by
anything and can be deleted: `kubectl delete secret admin-api-key`.)

##### Create a user
Role can be either "Utilisateur" or "Administrateur":
```
curl -X POST -H "Content-Type:multipart/form-data" -H "X-Admin-Key: $ADMIN_API_KEY" --form "username=admin" --form "password=testtest" --form "role=Administrateur" http://localhost/api/admin/signup
```

##### Get all users
```
curl -X POST -H "Content-Type:multipart/form-data" -H "X-Admin-Key: $ADMIN_API_KEY" http://localhost/api/admin/users
```

##### Change user password
Change a user's password without knowing the old one:
```
curl -X POST -H "Content-Type:multipart/form-data" -H "X-Admin-Key: $ADMIN_API_KEY" --form "username=admin" --form "new_password=testtest" http://localhost/api/admin/change_password
```

##### Delete user
Delete all data related to the given user as well as the user account itself:
```
curl -X POST -H "Content-Type:multipart/form-data" -H "X-Admin-Key: $ADMIN_API_KEY" --form "username=admin" http://localhost/api/admin/delete/user
```

##### Delete old tokens
"username" or "user_id" and "n_days_old" are optional. All tokens that are more than "n_days_old" days old are deleted:
```
curl -X POST -H "Content-Type:multipart/form-data" -H "X-Admin-Key: $ADMIN_API_KEY" --form "username=admin" --form "n_days_old=5" http://localhost/api/admin/delete/tokens
```

##### Delete old jobs
"username" or "user_id" is optional. All jobs that are more than "n_days_old" days old are deleted:
```
curl -X POST -H "Content-Type:multipart/form-data" -H "X-Admin-Key: $ADMIN_API_KEY" --form "username=admin" --form "n_days_old=5" http://localhost/api/admin/delete/jobs
```

##### Add default template
"user_id" is required. It will add the default templates defined on the server default_templates folder:
```
curl -X POST -H "Content-Type:multipart/form-data" -H "X-Admin-Key: $ADMIN_API_KEY" --form "user_id=admin" http://localhost/api/admin/template
```

##### Create an executor pod
It will add an empty job in the redis queue to trigger the creation of an executor pod.
```
curl -H "X-Admin-Key: $ADMIN_API_KEY" http://localhost/api/admin/executor
```
