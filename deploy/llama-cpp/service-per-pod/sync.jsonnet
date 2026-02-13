function(request) {
  local statefulset = request.object,
  local labelKey = statefulset.metadata.annotations["service-per-pod-label"],
  local ports = statefulset.metadata.annotations["service-per-pod-ports"],
  attachments: [
    {
      apiVersion: "v1",
      kind: "Service",
      metadata: {
        name: statefulset.metadata.name + "-" + index,
      },
      spec: {
        selector: {
          [labelKey]: statefulset.metadata.name + "-" + index,
        },
        ports: [
          { port: std.parseInt(p), targetPort: std.parseInt(p) }
          for p in std.split(ports, ",")
        ],
      },
    }
    for index in std.range(0, statefulset.spec.replicas - 1)
  ],
}
