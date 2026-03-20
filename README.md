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
[![Status](https://img.shields.io/badge/Status-WIP-f0884a?style=flat-square)]()

**Build infrastructure the way nature builds matter — atom by atom.**

[Philosophy](#-philosophy) · [Model](#-the-model) · [Structure](#-structure) · [Usage](#-usage) · [Roadmap](#-roadmap)

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
> *The minimum deployable unit.*

A single AWS service with its own Terraform files. Each atom is autonomous, independently versionable, and encapsulates all resources, variables, outputs, and IAM policies for **one service only**.

```
atoms/compute/lambda/
├── main.tf
├── variables.tf
└── outputs.tf
```

---

### ◈ Molecule — Level 02
> *A self-contained architectural blueprint.*

A combination of atoms that forms a coherent, independently deployable pattern. Molecules represent standard architectural building blocks — reusable across different applications.

```
molecules/swa/                  # Static Web App
├── main.tf                     # composes: cloudfront + s3 + waf
├── variables.tf
└── outputs.tf
```

| Molecule | Atoms |
|---|---|
| `swa` | `cloudfront` + `s3` + `waf` |
| `db` | `rds` + `sg` |
| `lambda-svc` | `lambda` + `sg` |

---

### ◆ Matter — Level 03
> *A complete, parameterized application.*

A composition of n molecules declared through a `composition.tfvars` file. Matter is not a simple variable — it is a **full material template** that defines the entire molecule stack and their configurations.

```hcl
# matter/three-tier-app/composition.tfvars

matter = "three-tier-app"

molecules = [
  {
    name   = "swa"
    atoms  = ["cloudfront", "s3", "waf"]
    config = {
      environment   = "prod"
      s3_versioning = true
      waf_ruleset   = "managed-core"
    }
  },
  {
    name   = "db"
    atoms  = ["rds", "sg"]
    config = {
      engine         = "postgres"
      instance_class = "db.t3.medium"
      multi_az       = true
    }
  },
  {
    name   = "lambda-svc"
    atoms  = ["lambda", "sg"]
    config = {
      runtime    = "python3.12"
      memory_mb  = 512
      timeout_s  = 30
    }
  }
]
```

---

## ◫ Structure

```
eif/
│
├── atoms/                          # Atomic AWS services
│   ├── compute/
│   │   ├── lambda/                 # main.tf · variables.tf · outputs.tf
│   │   └── ecs/
│   ├── networking/
│   │   ├── cloudfront/
│   │   └── api-gateway/
│   ├── storage/
│   │   ├── s3/
│   │   └── rds/
│   └── security/
│       ├── waf/
│       └── sg/
│
├── molecules/                      # Self-contained blueprints
│   ├── swa/                        # Static Web App
│   ├── db/                         # Database tier
│   └── lambda-svc/                 # Lambda service
│
└── matter/                         # Complete applications
    ├── three-tier-app/
    │   ├── composition.tfvars      # molecule stack + config
    │   ├── main.tf
    │   └── outputs.tf
    └── serverless-api/
        ├── composition.tfvars
        ├── main.tf
        └── outputs.tf
```

---

## ▶ Usage

### Deploy a matter

```bash
terraform init
terraform apply -var-file="matter/three-tier-app/composition.tfvars"
```

### Use a single molecule

```bash
cd molecules/swa
terraform init
terraform apply -var-file="my-env.tfvars"
```

### Use a single atom

```bash
cd atoms/storage/s3
terraform init
terraform apply
```

---

## ◎ Prerequisites

- Terraform `>= 1.5`
- AWS CLI configured with appropriate credentials
- An S3 backend bucket for remote state (recommended)

---

## ◌ Roadmap

- [ ] Atom library: compute, networking, storage, security
- [ ] Molecule library: `swa`, `db`, `lambda-svc`, `api-gw`
- [ ] Matter templates: `three-tier-app`, `serverless-api`
- [ ] Remote state management per matter
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
