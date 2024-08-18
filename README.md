# Reconaissance des matricules et notes

### User guide

- Add a front page to your copy, if necessary, to grade them
- Define a template to mark the zone where to search the grades and matricules (if necessary). If searching matricules, the app will also automatically search for the matricule on the top right corner of all pages except the front page.
- Start a new correction. If a column matching the regex '(?i)(gr|groupe?s?)$' is found, the corresponding content will be used to separate the copies into sub directories. The csv file must include a 'matricule' column as well as a 'Nom complet' column. Using a moodle csv file works immediately (you should fix the maximum grade).
- Then validate grades and matricules if necessary (it's not necessary if using directly moodle zip file or if each file contain it in its name).
- Then finalize and download the resulting cvs file, all the copies renamed and split into groups (if provided), and the zip files to upload to moodle (as well as the csv file).

### General information for installation

##### Nginx
You should deploy an nginx reverse proxy to point to the kubernetes server. You may adapt the nginx.conf file for this purpose (especially, enter your own certificate and set your server name).

##### Mongo
Mongo is run within the kubernetes cluster now.

##### Firebase
Firebase has been removed and a NFS (run inside the cluster) is instead used to synchronize and share files between containers, as well as persistent storage.

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
Do not use Keda 2.81, instead Keda 2.9.* as Kubernetes 1.20+ is only supported from 2.9:
```
kubectl apply -f https://github.com/kedacore/keda/releases/download/v2.9.3/keda-2.9.3.yaml
```

#### Deploy all services
Move to the deployment folder and run this command to start all services:
```
kubectl apply -f .
```

#### Modify deployment
Once a deployment yml file has been modified, you need to apply those modifications:
```
kubectl apply -f modified_deployment.yml
```
Then, to ensure the new pods are created, rollout the service for a deployment:
```
kubectl rollout restart deployment <modified deployment>
```
Or delete the corresponding pods for a Replication Controller:
```
kubectl delete pods <modified deployment pod>
```

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
The nfs connection may hang from time to time. To avoid this issue, we rollout the server pod every day with a cron job that will patch the server by modifying the date and trigger a rollout. To do so,, we create a service account 'cron' that we bind with the role edit to perform the patch operation. Then, the cron job daily rollout can de deploy and perform this action, as it uses the service account cron (see daily-rollout.yml). The minikube helper script can do those steps for you:
```
kubectl create sa cron
kubectl create clusterrolebinding cron --clusterrole edit --serviceaccount=default:cron
kubectl apply -f deployment/daily-rollout.yml
```

### Admin commands

They need to be run locally on the server (depending on nginx/ingress configuration).

##### Create a user
Role can be either "Utilisateur" or "Administrateur":
```
curl -X POST -H "Content-Type:multipart/form-data" --form "username=admin" --form "password=testtest" --form "role=Administrateur" http://localhost/api/admin/signup
```

##### Get all users
```
curl -X POST http://localhost/api/admin/users
```

##### Change user password
Change a user's password without knowing the old one:
```
curl -X POST -H "Content-Type:multipart/form-data" --form "username=admin" --form "new_password=testtest" http://localhost/api/admin/change_password
```

##### Delete user
Delete all data related to the given user as well as the user account itself:
```
curl -X POST -H "Content-Type:multipart/form-data" --form "username=admin" http://localhost/api/admin/delete/user
```

##### Delete old tokens
"username" or "user_id" and "n_days_old" are optional. All tokens that are more than "n_days_old" days old are deleted:
```
curl -X POST -H "Content-Type:multipart/form-data" --form "username=admin" --form "n_days_old=5" http://localhost/api/admin/delete/tokens
```

##### Delete old jobs
"username" or "user_id" is optional. All jobs that are more than "n_days_old" days old are deleted:
```
curl -X POST -H "Content-Type:multipart/form-data" --form "username=admin" --form "n_days_old=5" http://localhost/api/admin/delete/jobs
```

##### Add default template
"user_id" is required. It will add the default templates defined on the server default_templates folder:
```
curl -X POST -H "Content-Type:multipart/form-data" --form "user_id=admin" http://localhost/api/admin/template
```
