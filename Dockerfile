# Use an official Jenkins image as a parent image
FROM jenkins/jenkins:lts-jdk11

# Define Pachctl, Caddy versions
ENV PACHCTL_TAG_VER 1.12.5
ENV CADDY_TAG_VER 2.4.6
ENV K3S_VERSION v1.29.0+k3s1
ENV K3SUP_VERSION 0.13.5

# Switch to root to install additional packages
USER root

# Install Docker client
RUN curl -fsSL https://get.docker.com -o get-docker.sh && \
    chmod +x get-docker.sh && \
    sh get-docker.sh

# Install Ollama
RUN curl https://ollama.ai/install.sh | sh

# Set the working directory back if needed
WORKDIR /

# Install Caddy
RUN curl -L "https://github.com/caddyserver/caddy/releases/download/v${CADDY_TAG_VER}/caddy_${CADDY_TAG_VER}_linux_amd64.tar.gz" -o caddy.tar.gz && \
    tar -xvf caddy.tar.gz && \
    mv caddy /usr/local/bin/ && \
    rm caddy.tar.gz

# Install Pachctl only on amd64
RUN if [ "$(dpkg --print-architecture)" = "amd64" ]; then \
    curl -o /tmp/pachctl.deb -L https://github.com/pachyderm/pachyderm/releases/download/v${PACHCTL_TAG_VER}/pachctl_${PACHCTL_TAG_VER}_amd64.deb && \
    dpkg -i /tmp/pachctl.deb || true; \
    fi

# Install kubectl
RUN ARCH=$(dpkg --print-architecture) && curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/${ARCH}/kubectl" && \
    chmod +x kubectl && \
    mv kubectl /usr/local/bin/

# Add helm
RUN curl -fsSL -o get_helm.sh https://raw.githubusercontent.com/helm/helm/master/scripts/get-helm-3 \
    && chmod +x get_helm.sh && ./get_helm.sh

# Install iproute2 and avahi-daemon
RUN apt-get update && apt-get install -y iproute2 avahi-daemon

# Install k3sup
RUN curl -sLS https://get.k3sup.dev | sh

# Install gosu, pip, venv and ansible
RUN apt-get update && apt-get install -y gosu ansible sshpass python3-venv python3-pip jq libcap2-bin zip

# Create a virtual environment
RUN python3 -m venv /opt/venv

# Activate virtual environment
RUN . /opt/venv/bin/activate

# Install pipx in the virtual environment
# Note: We use /opt/venv/bin/pip to ensure we're installing pipx in the virtual environment
RUN /opt/venv/bin/pip install pipx

# Ensure pipx binaries are available system-wide (if necessary)
RUN ln -s /opt/venv/bin/pipx /usr/local/bin/pipx

# Further Python package installations should also use the virtual environment's pip
RUN /opt/venv/bin/pip install protobuf grpcio jupyter jupyterlab

# Download and install Nebula
RUN curl -L -o nebula.tar.gz https://github.com/slackhq/nebula/releases/download/v1.3.0/nebula-linux-amd64.tar.gz && \
    tar -xzvf nebula.tar.gz -C /usr/local/bin && \
    rm nebula.tar.gz

# Install the Jenkins CLI package
RUN curl -L https://github.com/jenkinsci/plugin-installation-manager-tool/releases/download/2.10.0/jenkins-plugin-manager-2.10.0.jar -o /opt/jenkins-plugin-manager.jar 

# Add the Jenkins Configuration as Code (JCasC) plugin
COPY plugins.txt /usr/share/jenkins/ref/plugins.txt

# Install plugins using plugins.txt
RUN java -jar /opt/jenkins-plugin-manager.jar --plugin-file /usr/share/jenkins/ref/plugins.txt --verbose

# Clean up apt cache for smaller image size
RUN apt-get clean && rm -rf /var/lib/apt/lists/*

# Switch back to the jenkins user
USER jenkins

# Skip initial setup
ENV JAVA_OPTS -Djenkins.install.runSetupWizard=false

# Add JCasC configuration file
COPY casc.yaml /usr/share/jenkins/ref/casc.yaml
ENV CASC_JENKINS_CONFIG /usr/share/jenkins/ref/casc.yaml
COPY Caddyfile /etc/caddy/Caddyfile

# Switch to root to set permissions
USER root

# Add and set permissions for the startup script
COPY startup.sh /startup.sh
RUN chmod +x /startup.sh

# Switch back to the jenkins user (or whichever user you wish to use)
USER jenkins

CMD ["/startup.sh"]
