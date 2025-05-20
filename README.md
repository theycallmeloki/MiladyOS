# MiladyOS

![127669 (1) (1) (1)](https://github.com/user-attachments/assets/4afc0590-a339-4989-8034-9d093b2d0581)



[![Twitter Follow](https://img.shields.io/twitter/follow/chillgates_?style=social)](https://twitter.com/chillgates_)


milady themed operations runner with optimized defaults for maximizing cpu+ram+gpu utilization accross a cluster

DISCLAIMER: This tool encapsulates what could be considered "best practices" for... bad practices.

As a distributed computing framework, MiladyOS enables the remote execution of arbitrary code. You should only install MiladyOS workers within networks that you trust. This is standard among distributed computing frameworks, but is worth repeating.

The client is able to download runners, greet milady neibours, create decentralized overlay networks, which then performs any number of Inference/Training tasks. This can potentially be used in a bad manner. Run the client with the least priviliges where possble. 

Find more information about the "principle of least privilege" on wikipedia: https://en.wikipedia.org/wiki/Principle_of_least_privilege

## Instructions to Run: 
You should have [Nvidia drivers](https://www.nvidia.com/download/index.aspx) installed and [nvidia-container-toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html) configured, post which it's recommended to reboot once prior to running this. 

```
curl -sSL https://raw.githubusercontent.com/theycallmeloki/MiladyOS/main/install_miladyos.sh | bash
```

The default username is `admin` and the default password is `password`


## Instructions to Build:

```
# docker buildx build --platform linux/amd64,linux/arm64 -t ogmiladyloki/miladyos --push .
```

## Instructions to Ingress (Proof-Of-Work - Full node): 

Look for the Caddyfile in the repo and update it to point to your domain
You would also set the A record to point to your IP address on your domain provider

```
yourfancydomain.com
```

TODO: Drop edith-cli dependency 

## Pachyderm bootrstrapped from [edith-cli](https://github.com/theycallmeloki/edith-cli)

### You will need [this script](https://gist.github.com/theycallmeloki/aa4df404c3df85c31dac91216e22f678) at the end of the edith-cli installation

Add the following to the Dockerfile in the root section and build yourself a container, checkout builder.sh

```
# Add kubeconfig file to the docker
ADD kubeconfig.yaml /root/.kube/config

# Add Pachctl config to the container
COPY config.json /root/.pachyderm/config.json
```
