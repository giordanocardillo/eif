<!-- EIF — Elemental Infrastructure Framework -->
<div align="center">

<img src="logo.svg" alt="EIF Logo" width="120" /><br><br>

<pre>
  E L E M E N T A L
I N F R A S T R U C T U R E
 F R A M E W O R K
</pre>

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-4af0c4?style=flat-square)](LICENSE)
[![Terraform](https://img.shields.io/badge/Terraform-≥1.5-3a8fff?style=flat-square&logo=terraform&logoColor=white)](https://www.terraform.io/)
[![Provider Agnostic](https://img.shields.io/badge/Provider-Agnostic-4af0c4?style=flat-square)](https://www.terraform.io/docs/providers/)
[![Python](https://img.shields.io/badge/Python-≥3.11-3a8fff?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![Status](https://img.shields.io/badge/Status-WIP-f0884a?style=flat-square)]()
[![Library](https://img.shields.io/badge/Component_Library-eif--library-4af0c4?style=flat-square)](https://github.com/giordanocardillo/eif-library)

**Build infrastructure the way nature builds matter — atom by atom.**

[Philosophy](#-philosophy) · [Model](#-the-model) · [Providers](#-providers) · [Structure](#-structure) · [Renderer](#-renderer) · [Environments](#-environments) · [Versioning](#-versioning) · [State](#-state) · [Usage](#-usage) · [Roadmap](#-roadmap)

</div>

---

## ◈ Philosophy

Modern cloud infrastructure suffers from two opposite extremes: the **monolith temptation** — a single Terraform repository that holds everything — and the **chaotic fragmentation** of disconnected modules without cohesion.

EIF proposes a third way, inspired by chemistry.

Every infrastructure resource has its own atomic identity, composable with precision into increasingly complex structures, up to fully deployable applications. The model is simple, the naming is intentional, the hierarchy is strict.

---

## ⬡ The Model

EIF organizes Terraform code into three hierarchical levels of abstraction:

### ◉ Atom — Level 01
> *Internal. Not user-facing.*

A single cloud service written in plain HCL. Atoms are the primitive building blocks of the framework — scoped to **one service only**. They are composed by molecules and are never deployed directly.

Atoms are namespaced by cloud provider: `atoms/aws/`, `atoms/azure/`, `atoms/gcp/`.

---

### ◈ Molecule — Level 02
> *Internal. Not user-facing.*

A combination of atoms forming a coherent architectural pattern. Intra-molecule atom dependencies are wired explicitly via output references — each atom that depends on another consumes its output directly. Molecules are never deployed directly.

Molecules are namespaced by cloud provider: `molecules/aws/`, `molecules/azure/`, `molecules/gcp/`.

| Molecule | Cloud | Atoms | Dependency chain |
|---|---|---|---|
| `single-page-application` | AWS | `s3` + `cloudfront` + `waf` | `cloudfront` ← `s3.domain`, `waf.arn` |
| `db` | AWS | `rds` + `sg` | `sg` port derived from engine → `rds` ← `sg.id` |
| `lambda-svc` | AWS | `lambda` + `sg` | `lambda` ← `sg.id` |
| `single-page-application` | Azure | `blob` + `frontdoor` | `frontdoor` ← `blob.primary_web_endpoint` |
| `single-page-application` | GCP | `gcs` + `cdn` + `armor` | `cdn` ← `gcs.bucket_name`, `armor.id` |

---

### ◆ Matter — Level 03
> *The only user-facing level.*

**Matter is the sole entry point for every deployment.** Even a deployment using a single molecule is expressed as a matter. Each matter has two types of input file:

- **`composition.json`** — stable structure: which molecules to include and which version to pin. Shared across all environments, only changes when the architecture changes.
- **`<env>.json`** — a flat pool of variables for that environment. No per-molecule grouping, no `environment` key — that is injected automatically by the renderer from the CLI argument.

```json
// composition.json — structure (environment-agnostic)
{
  "matter": "three-tier-app",
  "molecules": [
    { "name": "single-page-application", "source": "aws/single-page-application", "version": "1.0.0" },
    { "name": "db",                      "source": "aws/db",                      "version": "1.0.0" },
    { "name": "lambda-svc",              "source": "aws/lambda-svc",              "version": "1.0.0" }
  ]
}
```

```json
// prod.json — flat variable pool for production
{
  "account": "prod",

  "bucket_name": "my-app-assets-prod",
  "s3_versioning_enabled": true,
  "cloudfront_price_class": "PriceClass_100",

  "instance_class": "db.t3.medium",
  "multi_az": true,

  "vpc_id": "vpc-prod-id",
  "subnet_ids": ["subnet-a", "subnet-b"],

  "memory_mb": 512,
  "timeout_s": 30
}
```

The `eif` renderer injects `environment` automatically and makes all flat vars available to the Jinja2 template. The template is the wiring layer — it explicitly maps flat variables to each module's inputs, using `{{ src['mol-name'] }}` to reference the pinned source path.

---

## ◬ Providers

Providers are fully abstracted from the core framework. Each cloud provider lives in its own directory:

```
providers/
  aws/
    provider.tf.j2    ← terraform{} + provider "aws" block
  azure/
    provider.tf.j2    ← terraform{} + provider "azurerm" block
  gcp/
    provider.tf.j2    ← terraform{} + provider "google" block
```

Each `provider.tf.j2` receives the account config as Jinja2 context and renders the full `terraform {}` + `provider {}` block. The renderer **prepends this block automatically** to every rendered output — matter templates do not need to include it.

**Adding a new provider requires no changes to `eif.py` or any existing files** — just create `providers/<cloud>/provider.tf.j2`.

The `accounts.json` entry for each environment declares which provider to use:

```json
{
  "dev":        { "provider": "aws",   "aws_region": "us-east-1", "profile": "eif-dev" },
  "azure-dev":  { "provider": "azure", "subscription_id": "...",  "tenant_id": "..." },
  "gcp-prod":   { "provider": "gcp",   "project": "my-project",  "region": "us-central1" }
}
```

---

## ◫ Structure

This repository contains the **CLI tool only**. The component library lives in [eif-library](https://github.com/giordanocardillo/eif-library).

```
eif/                        ← this repo — the CLI tool
├── eif.py
├── pyproject.toml
└── examples/               ← reference implementation
    ├── accounts.example.json
    ├── providers/
    ├── atoms/
    ├── molecules/
    └── matters/
```

When using EIF in practice, your library repo follows this layout:

```
your-eif-library/
│
├── accounts.json                   # env → cloud account config
│
├── providers/                      # Cloud provider templates (pluggable)
│   ├── aws/
│   │   ├── provider.tf.j2          # terraform{} + provider "aws"
│   │   └── backend.tf.j2           # S3 backend block
│   ├── azure/
│   │   ├── provider.tf.j2
│   │   └── backend.tf.j2
│   └── gcp/
│       ├── provider.tf.j2
│       └── backend.tf.j2
│
├── atoms/                          # Atomic cloud services (plain HCL)
│   └── <cloud>/<category>/<name>/1.0.0/   # main.tf · variables.tf · outputs.tf
│
├── molecules/                      # Architectural blueprints
│   └── <cloud>/<name>/1.0.0/
│
└── matters/                        # Deployable applications
    └── <name>/<cloud>/
        ├── composition.json        # molecule list + pinned versions
        ├── <env>.json              # flat variable pool per environment
        └── main.tf.j2              # wiring template
```

---

## ◐ Renderer

The `eif` CLI takes a matter directory and an environment name. It:

1. Loads `accounts.json` from the repo root
2. Loads `composition.json` from the matter directory
3. Loads `<env>.json` from the matter directory
4. Renders `providers/<cloud>/provider.tf.j2` → `provider_block`
5. Builds a `src` dict mapping each molecule name to its resolved source path
6. Merges account config, flat env vars, and `environment` into the template context
7. Renders `main.tf.j2` → `.rendered/<env>/main.tf`
8. Prepends `provider_block` automatically — no `{{ provider_block }}` needed in templates

```
accounts.json            ──┐
providers/<cloud>/*.tf.j2  ┤
composition.json         ──┼──▶  eif  ──▶  .rendered/<env>/main.tf
<env>.json               ──┤
main.tf.j2               ──┘
```

---

## ◎ Environments

Each environment maps to a cloud account defined in `accounts.json`. The `provider` field determines which `providers/<cloud>/provider.tf.j2` is used:

```json
{
  "dev":  { "provider": "aws",   "aws_region": "us-east-1", "profile": "eif-dev" },
  "test": { "provider": "aws",   "aws_region": "us-east-1", "profile": "eif-test" },
  "prod": { "provider": "aws",   "aws_region": "us-east-1", "assume_role_arn": "arn:aws:iam::ACCOUNT_ID:role/EIFDeployRole" }
}
```

- `dev` and `test` authenticate via named AWS CLI profiles
- `prod` deploys to a separate AWS account via role assumption
- Azure and GCP accounts follow the same pattern with their own auth fields

---

## ◑ Versioning

Atoms and molecules are versioned using **semantic versioning** (`MAJOR.MINOR.PATCH`).

| Bump type | When to use | Example |
|---|---|---|
| `patch` | Bug fix, no interface change | `1.0.0` → `1.0.1` |
| `minor` | New optional variable or output | `1.0.0` → `1.1.0` |
| `major` | Breaking change (required var, type change, removed output) | `1.0.0` → `2.0.0` |

**The rule:** create a new version directory for every breaking change. Leave old versions in place — compositions pinned to them are unaffected.

```
atoms/aws/storage/rds/
  1.0.0/   ← existing matter stays pinned here
  2.0.0/   ← breaking: new required variable added
```

`eif new atom` and `eif new molecule` prompt for the bump type when a version already exists.

Each matter's `composition.json` pins exact versions per molecule:

```json
{
  "matter": "my-app",
  "molecules": [
    { "name": "db",  "source": "aws/db",  "version": "1.2.0" },
    { "name": "spa", "source": "aws/spa", "version": "3.0.0" }
  ]
}
```

`source` is `<provider>/<name>`. `version` is an exact semver pin — no ranges. The composition is the lock.

---

## ▶ Usage

### Prerequisites

- Python `>= 3.11` with [uv](https://docs.astral.sh/uv/)
- Terraform `>= 1.5`
- Cloud CLI configured with appropriate credentials or role

### Install

```bash
# install eif as a shell command
uv tool install git+https://github.com/giordanocardillo/eif

# or editable from a local clone (changes to eif.py take effect immediately)
uv tool install --editable .
```

Then initialise a new project:

```bash
# scaffold a new project (creates accounts.json, eif.particles.json, providers/, .gitignore, matters/)
eif init my-infra          # creates my-infra/ and initialises inside it
eif init                   # initialise in the current directory
```

`eif init [folder]` prompts for which cloud providers to include (aws / azure / gcp), writes provider templates, a pre-filled `accounts.json`, and `eif.particles.json`. If a folder name is provided it is created automatically. Fill in your credentials in `accounts.json` before deploying.

All `eif` commands are run from inside the project directory — `eif` finds the repo root by walking up to `accounts.json` or `eif.particles.json`.

### Render only

```bash
# interactive — select provider, matter, and environment from menus
eif render

# non-interactive — pass provider, matter, environment directly
eif render aws three-tier-app dev
```

### Preview upgrade safety

Before updating a molecule version, use `eif preview` to inspect what changed and whether it is breaking.

```bash
# atom — diffs the atom interface (variables + outputs) between two versions
eif preview atom aws storage/rds
eif preview atom aws storage/rds 1.0.0 2.0.0   # explicit range
eif preview atom                                 # fully interactive

# molecule — diffs the molecule interface between two versions
eif preview molecule aws db
eif preview molecule aws db 1.0.0 2.0.0
eif preview molecule                             # fully interactive

# matter — diffs all molecules in the composition against their latest registry versions
eif preview matter aws three-tier-app dev
eif preview matter                               # fully interactive

eif preview   # prompts: atom / molecule / matter
```

All three use git-diff style output — green for additions, red for removals, yellow for type/default changes. Breaking changes are flagged with `💥 BREAKING`. Pipe to a file for plain text: `eif preview matter aws my-app dev > report.txt`.

### Full deployment lifecycle

```bash
# plan — render + terraform plan (no changes applied)
eif plan aws three-tier-app dev

# plan with trivy scan (auto-runs if trivy is installed, blocks on CRITICAL/HIGH)
eif plan aws three-tier-app dev --scan

# apply — render + terraform init + apply + snapshot on success
eif apply aws three-tier-app dev

# apply with trivy scan
eif apply aws three-tier-app dev --scan

# destroy — terraform destroy against the last rendered output
eif destroy aws three-tier-app dev

# rollback — pick a previous snapshot and re-apply
eif rollback aws three-tier-app dev
```

When `--scan` is omitted, `plan` and `apply` prompt interactively if trivy is installed. If trivy is not on PATH, scanning is silently skipped.

All commands support interactive mode (no args) and non-interactive mode (`<provider> <matter> <env>`).

### Bootstrap remote state

```bash
# set up state bucket / container / DynamoDB table via cloud CLI
eif init backend aws three-tier-app dev

# add a new account entry to accounts.json (one-time, per account)
eif add account
```

### Manage particles

**Particles are molecules.** `eif particle` manages molecules explicitly — atoms are never installed directly; they are bundled automatically as dependencies when their parent molecule is installed.

`eif particle` installs molecules from a registry into a local `eif_particles/` cache (gitignored). This is an explicit step — like `npm install`.

```bash
# initialise registry config (one-time, creates eif.particles.json)
eif particle init

# download a molecule (installs to cache; also pins in composition.json if run inside a matter)
eif particle add aws/db
eif particle add aws/db 1.2.0          # or pin explicitly

# install all molecules referenced across all composition.json files
eif particle install

# update a molecule (shows diff, confirms, rewrites composition.json)
eif particle update aws/db
eif particle update                    # all molecules in current matter
eif particle update --safe             # skip major-version bumps

# inspect
eif particle list                      # show installed molecules
eif particle outdated                  # show available updates across all matters

# remove from composition.json (cache is shared — not deleted)
eif particle remove aws/db
```

`eif.particles.json` at the repo root configures the registry:

```json
{ "registry": "https://github.com/giordanocardillo/eif-library" }
```

If a molecule is missing when rendering, `eif` fails with a clear install message. Render and plan also print a non-blocking warning when newer versions are available in the registry.

### Cache

`eif_particles/` is a local download cache — gitignored and shared across all matters in the project. It can be safely deleted and rebuilt at any time.

```bash
eif cache clean   # shows size, confirms, then deletes eif_particles/
```

### Scaffold and remove components

```bash
# scaffold a new atom (prompts: name, provider, category)
eif new atom
eif new atom my-service       # name pre-filled

# scaffold a new molecule (prompts: name, provider)
eif new molecule
eif new molecule my-service

# scaffold a new matter — queries the registry live, selects molecules,
# installs them at their latest version, and pins them in composition.json
eif new matter
eif new matter my-app

# remove a local atom / molecule / matter (shows files, confirms before deleting)
eif remove atom
eif remove molecule aws db
eif remove matter aws my-app
```

First version starts at `1.0.0`. When a version already exists, `eif new` asks for the bump type (patch / minor / major) and computes the next version. Each scaffold emits starter `main.tf`, `variables.tf`, and `outputs.tf` (atoms/molecules) or `composition.json`, `dev.example.json`, `prod.example.json`, and `main.tf.j2` (matters).

Matter is the only deployment entry point. Atoms and molecules are internal — use them as building blocks, never deploy them directly.

---

## ⊙ State

EIF wraps the full Terraform deployment lifecycle. Every successful `apply` saves a **snapshot** of the rendered `main.tf`, enabling rollback to any previous configuration without touching the Terraform state file.

### Remote backends

Add a `backend` key to any account in `accounts.json` to enable remote state. EIF will inject the correct `backend {}` block into the rendered output automatically.

| Provider | Backend type | Required fields |
|---|---|---|
| AWS | `s3` | `bucket`, `region`, `dynamodb_table` (locking) |
| Azure | `azurerm` | `resource_group_name`, `storage_account_name`, `container_name` |
| GCP | `gcs` | `bucket` |

```json
// accounts.json — prod entry with S3 backend
{
  "prod": {
    "provider": "aws",
    "aws_region": "us-east-1",
    "assume_role_arn": "arn:aws:iam::...:role/EIFDeployRole",
    "backend": {
      "bucket":         "my-tfstate-bucket",
      "region":         "us-east-1",
      "dynamodb_table": "my-tfstate-locks"
    }
  }
}
```

If no `backend` is configured, Terraform uses local state and EIF stores snapshots in `.history/` (gitignored). This is suitable for solo developers; teams should configure a remote backend.

### Snapshot storage

- **Local** (always): `.history/<env>/<timestamp>/main.tf` — gitignored
- **Remote** (if backend configured): uploaded alongside state in the same bucket/container

### Rollback

Rollback restores a previous rendered `main.tf` and re-applies it. Terraform computes the diff against the current live state and converges the infrastructure accordingly.

---

## ◌ Roadmap

- [x] Jinja2 → HCL renderer (`eif render`)
- [x] Multi-environment and multi-account support
- [x] Multi-cloud provider abstraction (pluggable `providers/<cloud>/`)
- [x] Versioned atoms and molecules (semver `MAJOR.MINOR.PATCH`)
- [x] Scaffolding CLI (`eif new atom`, `eif new molecule`, `eif new matter`)
- [x] Deployment lifecycle (`eif plan`, `eif apply`, `eif destroy`, `eif rollback`)
- [x] Remote state management (S3 / Azure Blob / GCS backends)
- [x] Snapshot history and rollback
- [x] Backend bootstrap (`eif init backend`)
- [x] Vulnerability scanning (`eif scan` via Trivy — opt-in via `--scan` or interactive prompt)
- [x] Upgrade preview with breaking-change detection (`eif preview`)
- [x] Particle package manager (`eif particle` — install, add, update, outdated)
- [x] Registry configuration (`eif.particles.json` — local or remote GitHub URL)
- [x] Outdated alerts on render/plan/apply
- [x] Safe update mode (`eif particle update --safe` — skips major bumps)
- [x] Project scaffolding (`eif init` — providers, accounts.json, .gitignore, matters/)
- [x] Component removal (`eif remove atom`, `eif remove molecule`, `eif remove matter`)
- [x] Cache management (`eif cache clean`)
- [x] Download progress bar (apt-style `[████░░░░] X/N files`)
- [x] Provider block auto-prepended by renderer — no `{{ provider_block }}` in templates
- [ ] `eif particle publish` — publish local atoms/molecules to a registry
- [ ] CI/CD pipeline examples (GitHub Actions / Azure DevOps)
- [ ] Cost estimation integration
- [ ] OPA/policy-as-code hook before apply

---

## ⬡ Contributing

### Adding a new cloud provider

1. Create `providers/<cloud>/provider.tf.j2` with the `terraform {}` + `provider {}` block
2. Add atoms under `atoms/<cloud>/` following the existing category structure
3. Add molecules under `molecules/<cloud>/` composing those atoms
4. Add account entries to `accounts.json` with `"provider": "<cloud>"`

No changes to `eif.py` required.

### General contributions

Atoms, molecules, and matter contributions belong in [eif-library](https://github.com/giordanocardillo/eif-library). Please follow the existing file structure and naming conventions. Open an issue before submitting large structural changes.

---

## ◈ License

Apache 2.0 © [Giordano Cardillo](https://github.com/giordanocardillo)

---

<div align="center">
<sub>EIF · Elemental Infrastructure Framework · Provider Agnostic · Terraform</sub>
</div>
