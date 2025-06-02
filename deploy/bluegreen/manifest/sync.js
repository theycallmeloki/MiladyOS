/*
Copyright 2017 Google Inc.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    https://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
*/

const podTemplateAnnotation = 'bluegreendeployments.ctl.enisoc.com/pod-template-json';

var deepEqual = function (lhs, rhs) {
  if (typeof lhs === 'object' && typeof rhs === 'object') {
    for (let key in lhs) {
      if (!(key in rhs) || !deepEqual(lhs[key], rhs[key])) {
        return false;
      }
    }
    for (let key in rhs) {
      if (!(key in lhs)) {
        return false;
      }
    }
    return true;
  }
  return lhs === rhs;
};

var deepCopy = function (obj) {
  return obj ? JSON.parse(JSON.stringify(obj)) : null;
};

var hasReadWriteOnceVolumes = function (bgd) {
  if (!bgd.spec.template.spec.volumes) return false;
  
  return bgd.spec.template.spec.volumes.some(volume => {
    return volume.persistentVolumeClaim !== undefined;
  });
};

var isReplicaSetFullyTerminated = function (rs) {
  return rs && rs.spec.replicas === 0 && 
         rs.status && rs.status.replicas === 0 && 
         rs.status.readyReplicas === 0;
};

var podTemplateEqual = function (bgd, rs) {
  return rs && deepEqual(bgd.spec.template, JSON.parse(rs.metadata.annotations[podTemplateAnnotation]));
};

var newReplicaSet = function (bgd, color, replicas, template) {
  let rs = {
    apiVersion: 'apps/v1',
    kind: 'ReplicaSet',
    metadata: {
      name: `${bgd.metadata.name}-${color}`,
      labels: deepCopy(template.metadata.labels),
      annotations: {}
    },
    spec: {
      replicas: replicas,
      minReadySeconds: bgd.spec.minReadySeconds,
      selector: deepCopy(bgd.spec.selector),
      template: deepCopy(template)
    }
  };

  rs.metadata.labels.color = color;
  rs.metadata.annotations[podTemplateAnnotation] = JSON.stringify(template);
  rs.spec.selector.matchLabels = rs.spec.selector.matchLabels || {};
  rs.spec.selector.matchLabels.color = color;
  rs.spec.template.metadata.labels.color = color;

  return rs;
};

var newService = function (bgd, color) {
  let service = deepCopy(bgd.spec.service);
  service.apiVersion = 'v1';
  service.kind = 'Service';
  service.spec.selector.color = color;
  return service;
};

module.exports = async function (context) {
  let observed = context.request.body;
  let desired = {status: {}, children: []};

  console.log('observed: ' + observed)

  try {
    let bgd = observed.parent;
    let observedRS = observed.children['ReplicaSet.apps/v1'];

    // Compute status from observed state.
    let service = observed.children['Service.v1'][bgd.spec.service.metadata.name];
    let activeColor = service ? service.spec.selector.color : 'blue';

    let blueRS = observedRS[`${bgd.metadata.name}-blue`];
    let greenRS = observedRS[`${bgd.metadata.name}-green`];
    let [activeRS, inactiveRS] = (activeColor === 'blue') ? [blueRS, greenRS] : [greenRS, blueRS];

    desired.status = {
      activeColor: activeColor,
      active: activeRS ? activeRS.status : {},
      inactive: inactiveRS ? inactiveRS.status : {}
    };

    // Decide next step for rollout.
    let activeReplicas = activeRS ? activeRS.spec.replicas : bgd.spec.replicas;
    let activeTemplate = activeRS ? JSON.parse(activeRS.metadata.annotations[podTemplateAnnotation]) : bgd.spec.template;
    let inactiveReplicas = inactiveRS ? inactiveRS.spec.replicas : 0;
    let inactiveTemplate = inactiveRS ? JSON.parse(inactiveRS.metadata.annotations[podTemplateAnnotation]) : bgd.spec.template;

    // Check if we need volume-aware deployment (ReadWriteOnce volumes require special handling)
    let hasVolumeConstraints = hasReadWriteOnceVolumes(bgd);
    
    if (hasVolumeConstraints) {
      console.log('Volume constraints detected - using staged blue-green deployment');
    }

    // Is the active ReplicaSet based on the most up-to-date Pod template?
    if (podTemplateEqual(bgd, activeRS)) {
      // No rollout necessary. Scale down inactive.
      inactiveReplicas = 0;
    } else if (podTemplateEqual(bgd, inactiveRS)) {
      // The inactive RS already matches. Handle volume-aware rollout.
      if (hasVolumeConstraints) {
        // Volume-aware rollout: staged approach with proper termination waiting
        if (inactiveRS.status && inactiveRS.status.availableReplicas === bgd.spec.replicas) {
          // Stage 1: Inactive is ready, scale down active first to release volumes
          if (activeRS && activeRS.spec.replicas > 0) {
            console.log('Volume-aware stage 1: Scaling down active RS to release volumes');
            activeReplicas = 0;
            inactiveReplicas = bgd.spec.replicas;
          } else if (isReplicaSetFullyTerminated(activeRS)) {
            // Stage 2: Active is fully terminated (pods gone), safe to swap
            console.log('Volume-aware stage 2: Active RS fully terminated, swapping colors');
            activeColor = inactiveRS.metadata.labels.color;
            [activeReplicas, inactiveReplicas] = [bgd.spec.replicas, 0];
            [activeTemplate, inactiveTemplate] = [inactiveTemplate, activeTemplate];
          } else {
            // Still waiting for active pods to fully terminate
            console.log('Volume-aware: Waiting for active pods to fully terminate and release volumes');
            activeReplicas = 0;
            inactiveReplicas = bgd.spec.replicas;
          }
        } else {
          // Still scaling up inactive, don't touch active yet
          console.log('Volume-aware: Waiting for inactive RS to be ready before proceeding');
          inactiveReplicas = bgd.spec.replicas;
        }
      } else {
        // No volume constraints, use standard blue-green logic
        inactiveReplicas = bgd.spec.replicas;
        // Is it ready to swap?
        if (inactiveRS.status && inactiveRS.status.availableReplicas === bgd.spec.replicas) {
          // Swap active/inactive RS.
          activeColor = inactiveRS.metadata.labels.color;
          [activeReplicas, inactiveReplicas] = [inactiveReplicas, activeReplicas];
          [activeTemplate, inactiveTemplate] = [inactiveTemplate, activeTemplate];
        }
      }
    } else {
      // Neither RS matches.
      if (inactiveRS && inactiveRS.spec.replicas === 0 && inactiveRS.status && inactiveRS.status.replicas === 0) {
        // Start a new rollout.
        if (hasVolumeConstraints) {
          // For volume-constrained deployments, scale down active first
          if (activeRS && activeRS.spec.replicas > 0) {
            console.log('Volume-aware new rollout: Scaling down active RS first');
            activeReplicas = 0;
            inactiveReplicas = 0;
          } else if (!activeRS || isReplicaSetFullyTerminated(activeRS)) {
            // Active is fully terminated, safe to start inactive
            console.log('Volume-aware new rollout: Starting inactive RS');
            inactiveReplicas = bgd.spec.replicas;
            inactiveTemplate = bgd.spec.template;
          }
        } else {
          // No volume constraints, start rollout normally
          inactiveReplicas = bgd.spec.replicas;
          inactiveTemplate = bgd.spec.template;
        }
      } else {
        // Some other rollout was in progress. We need to cancel it and wait.
        inactiveReplicas = 0;
      }
    }

    // Generate desired children.
    desired.children = [
      newService(bgd, activeColor),
      newReplicaSet(bgd, activeColor, activeReplicas, activeTemplate),
      newReplicaSet(bgd, activeColor == 'blue' ? 'green' : 'blue', inactiveReplicas, inactiveTemplate)
    ];
  } catch (e) {
    return {status: 500, body: e.stack};
  }

  return {status: 200, body: desired, headers: {'Content-Type': 'application/json'}};
};
