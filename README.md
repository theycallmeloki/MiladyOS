# MiladyOS

![wp5487694-vegeta-4k-android-wallpapers (2)](https://github.com/theycallmeloki/MiladyOS/assets/3431687/ee97e609-e2fe-435f-a5c4-85d2a9d7f23f)



milady skinned jenkins with optimized defaults for maximizing gpu utilization across a cluster

DISCLAIMER: This tool encapsulates what could be considered "best practices" for... bad practices.

As a distributed computing framework, MiladyOS enables the remote execution of arbitrary code. You should only install MiladyOS workers within networks that you trust. This is standard among distributed computing frameworks, but is worth repeating.

The client is able to download runners, greet milady neibours, create decentralized overlay networks, which then performs any number of Inference/Training tasks. This can potentially be used in a bad manner. Run the client with the least priviliges where possble. 

Find more information about the "principle of least privilege" on wikipedia: https://en.wikipedia.org/wiki/Principle_of_least_privilege


## Instructions to Build:

```
# docker buildx build --platform linux/amd64,linux/arm64 -t ogmiladyloki/miladyos --push .
```

### If you don't have docker installed
```
sudo apt update && \
sudo apt install -y apt-transport-https ca-certificates curl software-properties-common && \
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo apt-key add - && \
sudo add-apt-repository "deb [arch=amd64] https://download.docker.com/linux/ubuntu focal stable" && \
sudo apt install -y docker-ce && \
sudo groupadd docker && \
sudo usermod -aG docker $USER && \
newgrp docker
```


## Instructions to Run: 
```
# docker run --gpus all -d --name miladyos --privileged --user root --restart=unless-stopped --net=host --env JENKINS_ADMIN_ID=admin --env JENKINS_ADMIN_PASSWORD=password -v /var/run/docker.sock:/var/run/docker.sock ogmiladyloki/miladyos
```

## Instructions to Ingress (Proof-Of-Work - Full node): 

Look for the Caddyfile in the repo and update it to point to your domain
You would also set the A record to point to your IP address on your domain provider

```
yourfancydomain.com
```

## Pachyderm bootrstrapped from [edith-cli](https://github.com/theycallmeloki/edith-cli)

### You will need [this script](https://gist.github.com/theycallmeloki/aa4df404c3df85c31dac91216e22f678) at the end of the edith-cli installation

Add the following to the Dockerfile in the root section and build yourself a container, checkout builder.sh

```
# Add kubeconfig file to the docker
ADD kubeconfig.yaml /root/.kube/config

# Add Pachctl config to the container
COPY config.json /root/.pachyderm/config.json
```
