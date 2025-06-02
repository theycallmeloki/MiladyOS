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

  console.log('=== BlueGreen Controller Sync Start ===');
  console.log(`Timestamp: ${new Date().toISOString()}`);
  console.log(`BGD Name: ${observed.parent?.metadata?.name || 'unknown'}`);
  console.log(`BGD Namespace: ${observed.parent?.metadata?.namespace || 'unknown'}`);
  console.log(`BGD Generation: ${observed.parent?.metadata?.generation || 'unknown'}`);
  console.log(`BGD Resource Version: ${observed.parent?.metadata?.resourceVersion || 'unknown'}`);
  console.log('observed: ' + JSON.stringify(observed, null, 2));

  try {
    let bgd = observed.parent;
    let observedRS = observed.children['ReplicaSet.apps/v1'];

    // Compute status from observed state.
    let service = observed.children['Service.v1'][bgd.spec.service.metadata.name];
    let activeColor = service ? service.spec.selector.color : 'blue';

    let blueRS = observedRS[`${bgd.metadata.name}-blue`];
    let greenRS = observedRS[`${bgd.metadata.name}-green`];
    let [activeRS, inactiveRS] = (activeColor === 'blue') ? [blueRS, greenRS] : [greenRS, blueRS];

    console.log(`Current State: activeColor=${activeColor}`);
    console.log(`Blue RS: ${blueRS ? `replicas=${blueRS.spec.replicas}, ready=${blueRS.status?.readyReplicas || 0}, available=${blueRS.status?.availableReplicas || 0}` : 'not found'}`);
    console.log(`Green RS: ${greenRS ? `replicas=${greenRS.spec.replicas}, ready=${greenRS.status?.readyReplicas || 0}, available=${greenRS.status?.availableReplicas || 0}` : 'not found'}`);
    console.log(`Active RS: ${activeRS?.metadata?.name || 'none'}, Inactive RS: ${inactiveRS?.metadata?.name || 'none'}`);

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
      console.log('🔒 VOLUME CONSTRAINTS DETECTED - using staged blue-green deployment');
      console.log('⚠️  ReadWriteOnce volumes require careful orchestration to prevent attachment failures');
      
      // Log current volume attachment state
      if (bgd.spec.template.spec.volumes) {
        console.log('📦 PVC volumes in BGD:');
        bgd.spec.template.spec.volumes.forEach((volume, idx) => {
          if (volume.persistentVolumeClaim) {
            console.log(`   ${idx}: ${volume.persistentVolumeClaim.claimName} -> ${volume.name}`);
          }
        });
      }
    } else {
      console.log('✅ No volume constraints - using standard blue-green deployment');
    }

    // Is the active ReplicaSet based on the most up-to-date Pod template?
    if (podTemplateEqual(bgd, activeRS)) {
      // No rollout necessary. Scale down inactive.
      console.log('✅ STEADY STATE: Active RS matches desired template, no rollout needed');
      console.log(`   Scaling down inactive RS to 0 replicas`);
      inactiveReplicas = 0;
    } else if (podTemplateEqual(bgd, inactiveRS)) {
      console.log('🔄 ROLLOUT IN PROGRESS: Inactive RS matches desired template');
      // The inactive RS already matches. Handle volume-aware rollout.
      if (hasVolumeConstraints) {
        console.log('🔒 Using VOLUME-AWARE rollout strategy to prevent volume attachment failures');
        // Volume-aware rollout: staged approach with proper termination waiting
        if (inactiveRS.status && inactiveRS.status.availableReplicas === bgd.spec.replicas) {
          // Stage 1: Inactive is ready, scale down active first to release volumes
          if (activeRS && activeRS.spec.replicas > 0) {
            console.log('📍 VOLUME-AWARE STAGE 1: Inactive RS ready, scaling down active RS to release volumes');
            console.log(`   Active RS ${activeRS.metadata.name}: ${activeRS.spec.replicas} -> 0 replicas`);
            console.log(`   ⚠️  This will release ReadWriteOnce volumes for reattachment`);
            activeReplicas = 0;
            inactiveReplicas = bgd.spec.replicas;
          } else if (isReplicaSetFullyTerminated(activeRS)) {
            // Stage 2: Active is fully terminated (pods gone), safe to swap
            console.log('🎯 VOLUME-AWARE STAGE 2: Active RS fully terminated, volumes released, swapping colors');
            console.log(`   Swapping: ${activeColor} -> ${inactiveRS.metadata.labels.color}`);
            console.log(`   ✅ Volumes are now safe to reattach to new active RS`);
            activeColor = inactiveRS.metadata.labels.color;
            [activeReplicas, inactiveReplicas] = [bgd.spec.replicas, 0];
            [activeTemplate, inactiveTemplate] = [inactiveTemplate, activeTemplate];
          } else {
            // Still waiting for active pods to fully terminate
            console.log('⏳ VOLUME-AWARE WAITING: Active pods still terminating, volumes not yet released');
            console.log(`   Active RS status: replicas=${activeRS.status?.replicas || 0}, ready=${activeRS.status?.readyReplicas || 0}`);
            console.log('   🚨 CRITICAL: Must wait for full termination to prevent volume attachment conflicts');
            activeReplicas = 0;
            inactiveReplicas = bgd.spec.replicas;
          }
        } else {
          // Still scaling up inactive, don't touch active yet
          console.log('⏳ VOLUME-AWARE PREP: Waiting for inactive RS to be fully ready before proceeding');
          console.log(`   Inactive RS status: ready=${inactiveRS.status?.readyReplicas || 0}/${bgd.spec.replicas}, available=${inactiveRS.status?.availableReplicas || 0}`);
          inactiveReplicas = bgd.spec.replicas;
        }
      } else {
        console.log('⚡ Using STANDARD blue-green rollout (no volume constraints)');
        // No volume constraints, use standard blue-green logic
        inactiveReplicas = bgd.spec.replicas;
        // Is it ready to swap?
        if (inactiveRS.status && inactiveRS.status.availableReplicas === bgd.spec.replicas) {
          console.log('🎯 STANDARD SWAP: Inactive RS ready, performing immediate color swap');
          console.log(`   Swapping: ${activeColor} -> ${inactiveRS.metadata.labels.color}`);
          // Swap active/inactive RS.
          activeColor = inactiveRS.metadata.labels.color;
          [activeReplicas, inactiveReplicas] = [inactiveReplicas, activeReplicas];
          [activeTemplate, inactiveTemplate] = [inactiveTemplate, activeTemplate];
        } else {
          console.log('⏳ STANDARD PREP: Inactive RS scaling up, waiting for readiness');
          console.log(`   Inactive RS status: ready=${inactiveRS.status?.readyReplicas || 0}/${bgd.spec.replicas}, available=${inactiveRS.status?.availableReplicas || 0}`);
        }
      }
    } else {
      console.log('🚀 NEW ROLLOUT: Neither RS matches desired template - starting fresh rollout');
      // Neither RS matches.
      if (inactiveRS && inactiveRS.spec.replicas === 0 && inactiveRS.status && inactiveRS.status.replicas === 0) {
        // Start a new rollout.
        if (hasVolumeConstraints) {
          console.log('🔒 NEW VOLUME-AWARE ROLLOUT: Must scale down active first to release volumes');
          // For volume-constrained deployments, scale down active first
          if (activeRS && activeRS.spec.replicas > 0) {
            console.log('📍 VOLUME-AWARE NEW STAGE 1: Scaling down active RS to release volumes for new rollout');
            console.log(`   Active RS ${activeRS.metadata.name}: ${activeRS.spec.replicas} -> 0 replicas`);
            console.log('   ⚠️  Must complete before starting new inactive RS to prevent volume conflicts');
            activeReplicas = 0;
            inactiveReplicas = 0;
          } else if (!activeRS || isReplicaSetFullyTerminated(activeRS)) {
            // Active is fully terminated, safe to start inactive
            console.log('🎯 VOLUME-AWARE NEW STAGE 2: Active RS terminated, volumes released, starting new inactive RS');
            console.log(`   Starting inactive RS with new template (generation ${bgd.metadata.generation})`);
            console.log('   ✅ Volumes are now safe for new rollout');
            inactiveReplicas = bgd.spec.replicas;
            inactiveTemplate = bgd.spec.template;
          }
        } else {
          console.log('⚡ STANDARD NEW ROLLOUT: Starting inactive RS immediately (no volume constraints)');
          // No volume constraints, start rollout normally
          inactiveReplicas = bgd.spec.replicas;
          inactiveTemplate = bgd.spec.template;
        }
      } else {
        // Some other rollout was in progress. We need to cancel it and wait.
        console.log('🛑 ROLLOUT CONFLICT: Another rollout in progress, canceling and waiting');
        console.log(`   Inactive RS status: replicas=${inactiveRS?.spec?.replicas || 0}, actual=${inactiveRS?.status?.replicas || 0}`);
        inactiveReplicas = 0;
      }
    }

    // Generate desired children.
    console.log('🎯 FINAL STATE DECISION:');
    console.log(`   Service color: ${activeColor}`);
    console.log(`   Active RS (${activeColor}): ${activeReplicas} replicas`);
    console.log(`   Inactive RS (${activeColor == 'blue' ? 'green' : 'blue'}): ${inactiveReplicas} replicas`);
    
    desired.children = [
      newService(bgd, activeColor),
      newReplicaSet(bgd, activeColor, activeReplicas, activeTemplate),
      newReplicaSet(bgd, activeColor == 'blue' ? 'green' : 'blue', inactiveReplicas, inactiveTemplate)
    ];
    
    console.log('✅ SYNC COMPLETE - Desired state generated');
    console.log('=== BlueGreen Controller Sync End ===');
  } catch (e) {
    return {status: 500, body: e.stack};
  }

  return {status: 200, body: desired, headers: {'Content-Type': 'application/json'}};
};
