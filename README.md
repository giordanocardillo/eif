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

**Build infrastructure the way nature builds matter — atom by atom.**

[Philosophy](#-philosophy) · [Model](#-the-model) · [Providers](#-providers) · [Structure](#-structure) · [Renderer](#-renderer) · [Environments](#-environments) · [Versioning](#-versioning) · [Usage](#-usage) · [Roadmap](#-roadmap)

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
    { "name": "single-page-application", "source": "molecules/aws/single-page-application/v1" },
    { "name": "db",                      "source": "molecules/aws/db/v1" },
    { "name": "lambda-svc",              "source": "molecules/aws/lambda-svc/v1" }
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

Each `provider.tf.j2` receives the account config as Jinja2 context and renders the full `terraform {}` + `provider {}` block. The rendered output is injected into the matter template as `{{ provider_block }}`.

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

```
eif/
│
├── accounts.json                   # env → cloud account config
├── eif.py                          # renderer CLI
├── pyproject.toml                  # Python project (uv / hatchling)
│
├── providers/                      # Cloud provider templates (pluggable)
│   ├── aws/provider.tf.j2          # terraform{} + provider "aws"
│   ├── azure/provider.tf.j2        # terraform{} + provider "azurerm"
│   └── gcp/provider.tf.j2          # terraform{} + provider "google"
│
├── atoms/                          # Atomic cloud services (plain HCL)
│   ├── aws/
│   │   ├── compute/lambda/v1/      # main.tf · variables.tf · outputs.tf
│   │   ├── networking/cloudfront/v1/
│   │   ├── storage/s3/v1/ · storage/rds/v1/
│   │   └── security/waf/v1/ · security/sg/v1/
│   ├── azure/
│   │   ├── storage/blob/v1/
│   │   └── networking/frontdoor/v1/
│   └── gcp/
│       ├── storage/gcs/v1/
│       ├── networking/cdn/v1/
│       └── security/armor/v1/
│
├── molecules/                      # Architectural blueprints
│   ├── aws/
│   │   ├── single-page-application/v1/   # s3/v1 + cloudfront/v1 + waf/v1
│   │   ├── db/v1/                        # rds/v1 + sg/v1
│   │   └── lambda-svc/v1/               # lambda/v1 + sg/v1
│   ├── azure/
│   │   └── single-page-application/v1/   # blob/v1 + frontdoor/v1
│   └── gcp/
│       └── single-page-application/v1/   # gcs/v1 + cdn/v1 + armor/v1
│
└── matters/                        # Deployable applications
    ├── three-tier-app/
    │   └── aws/
    │       ├── composition.json    # molecule list + pinned versions (stable)
    │       ├── dev.json · test.json · prod.json
    │       ├── main.tf.j2          # Jinja2 template
    │       └── .rendered/          # gitignored — render artifacts
    └── single-page-application/
        ├── aws/
        ├── azure/
        └── gcp/
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

Atoms and molecules are versioned via subdirectories (`v1/`, `v2/`, ...). This guarantees that matter already in production is never broken by new feature work.

**The rule:**

| Change type | Action |
|---|---|
| Bug fix, new optional variable | Edit in place within the existing version |
| Breaking change (remove var, change type, restructure outputs) | Create a new version directory alongside the old one |

**Example — adding a breaking change to an atom:**

```
atoms/aws/storage/s3/
  v1/   ← existing production matter stays pinned here
  v2/   ← new interface; new molecules reference this
```

The molecule that needs the new feature gets its own `v2/` referencing `atoms/aws/storage/s3/v2`. All existing matter compositions continue to pin `molecules/aws/single-page-application/v1` and are completely unaffected.

Molecule sources are pinned in `composition.json`:

```json
{ "name": "single-page-application", "source": "molecules/aws/single-page-application/v1" }
```

To bump all pinned molecule versions in `composition.json` to the latest available:

```bash
uv run eif upgrade matters/three-tier-app/aws dev
```

---

## ▶ Usage

### Prerequisites

- Python `>= 3.11` with [uv](https://docs.astral.sh/uv/)
- Terraform `>= 1.5`
- Cloud CLI configured with appropriate credentials or role

### Install

```bash
uv sync
```

### Render and deploy

```bash
# interactive — select provider, matter, and environment from menus
uv run eif render

# non-interactive — pass provider, matter, environment directly
uv run eif render aws three-tier-app dev

# deploy
terraform -chdir=matters/three-tier-app/aws/.rendered/dev init
terraform -chdir=matters/three-tier-app/aws/.rendered/dev apply
```

### Upgrade molecule versions

```bash
# interactive
uv run eif upgrade

# non-interactive
uv run eif upgrade aws three-tier-app dev
```

### Scaffold new components

The `eif new` commands interactively scaffold atoms, molecules, and matters. They detect available providers from `providers/`, check for existing versions, and create the correct directory structure with starter files.

```bash
# scaffold a new atom (prompts: name, provider, category)
uv run eif new atom
uv run eif new atom my-service       # name pre-filled

# scaffold a new molecule (prompts: name, provider)
uv run eif new molecule
uv run eif new molecule my-service

# scaffold a new matter (prompts: name, provider)
uv run eif new matter
uv run eif new matter my-app
```

If the atom or molecule already exists the command reports the latest version and asks whether to create the next one (e.g. `v2`). Each scaffold emits starter `main.tf`, `variables.tf`, and `outputs.tf` (atoms/molecules) or `composition.json`, `dev.example.json`, `prod.example.json`, and `main.tf.j2` (matters).

Matter is the only deployment entry point. Atoms and molecules are internal — use them as building blocks when authoring new matter templates, never deploy them directly.

---

## ◌ Roadmap

- [x] Atom library (AWS): `s3`, `cloudfront`, `waf`, `lambda`, `rds`, `sg`
- [x] Molecule library (AWS): `single-page-application`, `db`, `lambda-svc`
- [x] Matter template: `three-tier-app` (AWS — `single-page-application` + `db` + `lambda-svc`)
- [x] Jinja2 → HCL renderer (`eif`)
- [x] Multi-environment support (`dev`, `test`, `prod`)
- [x] Multi-account support (profile + assume_role)
- [x] Versioned atoms and molecules (`v1/`, upgrade CLI)
- [x] Multi-cloud provider abstraction (AWS, Azure, GCP — pluggable)
- [x] Atom + molecule library: Azure (`blob`, `frontdoor` → `single-page-application`)
- [x] Atom + molecule library: GCP (`gcs`, `cdn`, `armor` → `single-page-application`)
- [x] Matter template: `single-page-application` (AWS, Azure, GCP)
- [x] Scaffolding CLI: `eif new atom`, `eif new molecule`, `eif new matter`
- [ ] Atom library (AWS): compute (`ecs`), networking (`api-gateway`)
- [ ] Matter template: `serverless-api`
- [ ] Remote state management per matter/environment
- [ ] CI/CD pipeline examples (GitHub Actions / Azure DevOps)
- [ ] Tagging strategy module
- [ ] Cost estimation per matter

---

## ⬡ Contributing

### Adding a new cloud provider

1. Create `providers/<cloud>/provider.tf.j2` with the `terraform {}` + `provider {}` block
2. Add atoms under `atoms/<cloud>/` following the existing category structure
3. Add molecules under `molecules/<cloud>/` composing those atoms
4. Add account entries to `accounts.json` with `"provider": "<cloud>"`

No changes to `eif.py` required.

### General contributions

Atoms, molecules, and matter contributions are welcome. Please follow the existing file structure and naming conventions. Open an issue before submitting large structural changes.

---

## ◈ License

Apache 2.0 © [Giordano Cardillo](https://github.com/giordanocardillo)

---

<div align="center">
<sub>EIF · Elemental Infrastructure Framework · Provider Agnostic · Terraform</sub>
</div>
