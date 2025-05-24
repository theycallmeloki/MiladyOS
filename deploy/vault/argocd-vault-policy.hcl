path "secret/data/argocd/*" {
  capabilities = ["read", "list"]
}

path "secret/metadata/argocd/*" {
  capabilities = ["list"]
}