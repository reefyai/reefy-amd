# Reefy AMD provider

This repository builds Reefy's on-demand AMD GPU host extension. Each
published OCI artifact is tied to one exact Reefy kernel build and contains:

- AMD GPU Driver 31.40 external kernel modules;
- the matching complete AMD GPU firmware set;
- AMD Container Toolkit's `amd-ctk` for CDI generation;
- a minimal `amd-smi` host diagnostic; and
- the provider-owned activation hook.

ROCm, HIP, Mesa, media, and application libraries stay in application images.
The matching Reefy OS supplies Buildroot's generic libdrm and AMD backend for
the host `amd-smi` diagnostic.
The provider is mounted read-only and activated by Reefy OS without a
long-running driver container.

Artifacts are published to `ghcr.io/reefyai/reefy-amd` by the reusable
workflow. Tags are for discovery. Devices always receive an exact digest from
the firmware provider catalog.
