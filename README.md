<!-- EIF — Elemental Infrastructure Framework -->
<div align="center">

<pre>
  ◉
  E L E M E N T A L
I N F R A S T R U C T U R E
 F R A M E W O R K
  ◉
</pre>

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-4af0c4?style=flat-square)](LICENSE)
[![Terraform](https://img.shields.io/badge/Terraform-≥1.5-3a8fff?style=flat-square&logo=terraform&logoColor=white)](https://www.terraform.io/)
[![AWS](https://img.shields.io/badge/Provider-AWS-f0884a?style=flat-square&logo=amazon-aws&logoColor=white)](https://registry.terraform.io/providers/hashicorp/aws)
[![Python](https://img.shields.io/badge/Python-≥3.11-3a8fff?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![Status](https://img.shields.io/badge/Status-WIP-f0884a?style=flat-square)]()

**Build infrastructure the way nature builds matter — atom by atom.**

[Philosophy](#-philosophy) · [Model](#-the-model) · [Structure](#-structure) · [Renderer](#-renderer) · [Environments](#-environments) · [Usage](#-usage) · [Roadmap](#-roadmap)

</div>

---

## ◈ Philosophy

Modern cloud infrastructure suffers from two opposite extremes: the **monolith temptation** — a single Terraform repository that holds everything — and the **chaotic fragmentation** of disconnected modules without cohesion.

EIF proposes a third way, inspired by chemistry.

Every AWS resource has its own atomic identity, composable with precision into increasingly complex structures, up to fully deployable applications. The model is simple, the naming is intentional, the hierarchy is strict.

---

## ⬡ The Model

EIF organizes Terraform code into three hierarchical levels of abstraction:

### ◉ Atom — Level 01
> *Internal. Not user-facing.*

A single AWS service written in plain HCL. Atoms are the primitive building blocks of the framework — scoped to **one service only**. They are composed by molecules and are never deployed directly.

---

### ◈ Molecule — Level 02
> *Internal. Not user-facing.*

A combination of atoms forming a coherent architectural pattern. Intra-molecule atom dependencies are wired explicitly via output references — each atom that depends on another consumes its output directly. Molecules are never deployed directly.

| Molecule | Atoms | Dependency chain |
|---|---|---|
| `swa` | `s3` + `cloudfront` + `waf` | `cloudfront` ← `s3.domain`, `waf.arn` |
| `db` | `rds` + `sg` | `sg` port derived from engine → `rds` ← `sg.id` |
| `lambda-svc` | `lambda` + `sg` | `lambda` ← `sg.id` |

---

### ◆ Matter — Level 03
> *The only user-facing level.*

**Matter is the sole entry point for every deployment.** Even a deployment using a single molecule is expressed as a matter. Each matter has one JSON composition file per environment. The `eif` renderer merges it with the account config and produces ready-to-apply HCL.

```json
{
  "matter": "three-tier-app",
  "account": "prod",
  "molecules": [
    {
      "name": "swa",
      "source": "molecules/swa",
      "config": {
        "environment": "prod",
        "bucket_name": "my-app-assets-prod",
        "s3_versioning_enabled": true,
        "waf_name": "my-app-waf"
      }
    }
  ]
}
```

---

## ◫ Structure

```
eif/
│
├── accounts.json                   # env → AWS account config (profile / assume_role)
├── eif.py                          # renderer CLI
├── pyproject.toml                  # Python project (uv / hatchling)
│
├── atoms/                          # Atomic AWS services (plain HCL)
│   ├── compute/
│   │   └── lambda/                 # main.tf · variables.tf · outputs.tf
│   ├── networking/
│   │   └── cloudfront/
│   ├── storage/
│   │   ├── s3/
│   │   └── rds/
│   └── security/
│       ├── waf/
│       └── sg/
│
├── molecules/                      # Architectural blueprints
│   ├── swa/                        # s3 + cloudfront + waf
│   ├── db/                         # rds + sg
│   └── lambda-svc/                 # lambda + sg
│
└── matter/                         # Deployable applications
    └── three-tier-app/
        ├── dev.json                # environment composition (input)
        ├── test.json
        ├── prod.json
        ├── main.tf.j2              # Jinja2 template
        └── .rendered/              # gitignored — render artifacts
            ├── dev/main.tf
            ├── test/main.tf
            └── prod/main.tf
```

---

## ◐ Renderer

The `eif` CLI takes a matter directory and an environment name. It:

1. Loads `accounts.json` from the repo root
2. Loads `<env>.json` from the matter directory
3. Resolves molecule source paths relative to the render output directory
4. Merges account config into the template context
5. Renders `main.tf.j2` → `.rendered/<env>/main.tf`

```
accounts.json  ──┐
<env>.json     ──┼──▶  eif  ──▶  .rendered/<env>/main.tf
main.tf.j2     ──┘
```

---

## ◎ Environments

Each environment maps to an AWS account defined in `accounts.json`:

```json
{
  "dev":  { "aws_region": "us-east-1", "profile": "eif-dev" },
  "test": { "aws_region": "us-east-1", "profile": "eif-test" },
  "prod": { "aws_region": "us-east-1", "assume_role_arn": "arn:aws:iam::ACCOUNT_ID:role/EIFDeployRole" }
}
```

- `dev` and `test` authenticate via named AWS CLI profiles
- `prod` deploys to a separate AWS account via role assumption

The rendered provider block reflects the account config automatically:

```hcl
# dev / test
provider "aws" {
  region  = "us-east-1"
  profile = "eif-dev"
}

# prod
provider "aws" {
  region = "us-east-1"
  assume_role {
    role_arn = "arn:aws:iam::ACCOUNT_ID:role/EIFDeployRole"
  }
}
```

---

## ▶ Usage

### Prerequisites

- Python `>= 3.11` with [uv](https://docs.astral.sh/uv/)
- Terraform `>= 1.5`
- AWS CLI configured with appropriate credentials or role

### Install

```bash
uv sync
```

### Render and deploy

```bash
# render for a specific environment
uv run eif matter/three-tier-app dev
uv run eif matter/three-tier-app prod

# deploy
terraform -chdir=matter/three-tier-app/.rendered/dev init
terraform -chdir=matter/three-tier-app/.rendered/dev apply
```

Matter is the only deployment entry point. Atoms and molecules are internal — use them as building blocks when authoring new matter templates, never deploy them directly.

---

## ◌ Roadmap

- [x] Atom library: `s3`, `cloudfront`, `waf`, `lambda`, `rds`, `sg`
- [x] Molecule library: `swa`, `db`, `lambda-svc`
- [x] Matter template: `three-tier-app` (`swa` + `db` + `lambda-svc`)
- [x] Jinja2 → HCL renderer (`eif`)
- [x] Multi-environment support (`dev`, `test`, `prod`)
- [x] Multi-account support (profile + assume_role)
- [ ] Atom library: compute (`ecs`), networking (`api-gateway`)
- [ ] Matter template: `serverless-api`
- [ ] Remote state management per matter/environment
- [ ] CI/CD pipeline examples (GitHub Actions / Azure DevOps)
- [ ] Tagging strategy module
- [ ] Cost estimation per matter

---

## ⬡ Contributing

Atoms, molecules, and matter contributions are welcome. Please follow the existing file structure and naming conventions. Open an issue before submitting large structural changes.

---

## ◈ License

Apache 2.0 © [Giordano Cardillo](https://github.com/giordanocardillo)

---

<div align="center">
<sub>EIF · Elemental Infrastructure Framework · AWS · Terraform</sub>
</div>
