# Idea: every Harvis provisions its own Kubernetes, and becomes a LAN host

**Status:** idea only. Nothing built. Direction is clear, scope is not — see "Open questions".
**Raised:** 2026-08-28

## The idea

Harvis should be able to **install Kubernetes onto the user's own machine** and manage it, so that
each Harvis instance turns its host into a small self-hosted platform. The user then hosts tools
on it and **shares them with other people on their network**.

The important word is *becomes*. Harvis today runs *on* Kubernetes when an operator supplies a
cluster — `harvis-helm-chart/` opens with "Prerequisites: Kubernetes 1.19+", i.e. you bring the
cluster and Harvis is a tenant in it. This idea is the other direction: Harvis brings the cluster,
the user's laptop or box is the infrastructure, and the output is a hosting service that other
people can reach.

So a user goes from "I run an AI assistant" to "I run a small private cloud, and my friends can
use the tools on it."

## Why this is a different feature from what exists

It is easy to look at `harvis-helm-chart/`, `k8s-manifests/`, the Flux and Argo setups and
conclude this is mostly done. It is not, and the gap is worth stating plainly:

| Exists today | What this idea needs |
|---|---|
| Deploy Harvis into a cluster someone else runs | Create and own the cluster on the user's own hardware |
| Operator runs `helm install` by hand | Harvis installs, upgrades and heals it unattended |
| One tenant: Harvis | Many tenants: arbitrary user-chosen tools |
| Reachable wherever the operator exposed it | Discoverable by other people on the LAN |
| The operator is an admin who knows k8s | The user must never need to know k8s exists |

Roughly none of the hard parts of this idea are the parts already built.

## Why it should be worth doing

- **It makes Harvis infrastructure rather than an app.** A Harvis that hosts things for other
  people is much harder to replace than one that answers questions.
- **Sharing is the actual goal.** The stated point is to share with others and host tools. A single
  user's local Docker Compose cannot do that; a cluster with an ingress and LAN discovery can.
- **Tools stop being Harvis-internal.** Anything packaged as a container becomes something a user
  can offer to their household, team or friends, without any of it touching a cloud provider.
- **It reuses work already done.** The Helm chart, the Flux GitOps layer and the container images
  are all assets here. They just get pointed at a cluster Harvis created instead of one it found.

## Shape it would probably take

Not designed — this is the sketch to argue with.

- **k3s, almost certainly, not upstream Kubernetes.** Single binary, single-node by default, runs
  in a few hundred MB, installs unattended, and is a conformant cluster. Upstream kubeadm on a
  user's laptop is not a serious proposition. This also means "throw it on their system" is a real
  one-command operation rather than a project.
- **Harvis owns the cluster lifecycle** — install, upgrade, restart on boot, tear down cleanly.
  Users should be able to uninstall and get their machine back.
- **A tool catalog.** Users pick from things Harvis knows how to deploy, rather than authoring
  manifests. Each entry is an image plus the small amount of config that makes it reachable.
- **LAN reachability without DNS admin.** An ingress plus mDNS/Avahi so tools appear as
  `something.local` to everyone on the network, with no router configuration.
- **Sharing as a first-class concept**, not a side effect of binding to 0.0.0.0 — who can see a
  tool, and who can use it, has to be an explicit choice at the moment of hosting.

## Where it would attach in Harvis

Existing pieces this touches:

- `harvis-helm-chart/` — the chart itself is reusable; its prerequisites section is the thing that
  changes, because Harvis would now be satisfying its own prerequisite.
- `k8s-manifests/` with `flux/`, `flux-system/`, `argocd/` — a GitOps layer already exists. Whether
  a single-user LAN cluster wants GitOps or something much simpler is an open question, not a given.
- `deploy-k8s-services.sh` — the closest existing thing to an automated bring-up; worth reading
  before designing the installer, since it likely already encodes hard-won ordering details.
- The engine sidecars in `docker-compose.yaml` — today they are Compose services. On a cluster they
  become workloads, and that is a real migration, not a rename.

## Relevant prior art already vendored

From the resource sweep in `~/Projects/resource-grabber` — these were catalogued before this idea
was raised, and three of them turn out to point straight at it:

- **`kagent`** (CNCF sandbox, Apache-2.0, Go) — agents, model configs and MCP tool servers declared
  as Kubernetes CRDs, with a controller supervising them. This is the closest existing answer to
  "tools as declarative objects on a small cluster", and it targets k3s. Previously filed as
  "needs k3s", which read as a cost. Under this idea it is the point.
- **`docker-agent`** (Apache-2.0, Go) — agent definitions distributed as OCI artifacts, pushed and
  pulled like container images. That is a ready-made answer to how a tool catalog gets shipped and
  updated without Harvis hosting a registry of its own.
- **`toolhive`** — MCP server hosting, already vendored. Relevant to the "host tools" half.

This is also the clearest case so far of the corpus paying for itself: the idea arrived after the
sweep, and the sweep already had the material.

## Open questions

- **What does "share with others" actually mean?** LAN-only is a very different security problem
  from anything reachable off the local network. Everything downstream — auth, identity, exposure,
  update policy — depends on this answer, and it should be settled first.
- **Who are the others?** Anonymous devices on the same wifi, named people with accounts, or other
  Harvis instances? "Other Harvises federate" is a much bigger idea hiding inside this one.
- **Is this one node or several?** "Each Harvis makes their own" reads single-node. If two users on
  the same LAN should pool machines into one cluster, that is a different product.
- **What happens on a laptop that sleeps, moves networks, or runs out of battery?** A host that is
  only sometimes present is the normal case here, not the exception, and it breaks most assumptions
  a cluster makes about itself.
- **How much does the cluster cost the user's machine at idle?** If hosting makes their own Harvis
  slower, they will turn it off. There is a real budget here and it should be measured, not assumed.
- **Does GPU workload scheduling come along?** The host has one GPU that the desktop is already
  using. Hosting a tool that wants it is a conflict, not a scheduling problem.
- **What is the trust model for catalog tools?** Running arbitrary community containers on a user's
  personal machine, reachable by other people, is the highest-risk thing in this note.

## What's missing

The security posture, before anything else. This idea takes a personal machine and turns it into a
service other people connect to, which is a category change in exposure and cannot be retrofitted.
Decide the sharing boundary — LAN-only versus wider — and the tool trust model, and the rest of the
design follows from those two answers.
