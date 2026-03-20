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

[Philosophy](#-philosophy) · [Model](#-the-model) · [Structure](#-structure) · [Renderer](#-renderer) · [Usage](#-usage) · [Roadmap](#-roadmap)

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

A combination of atoms forming a coherent architectural pattern. Molecules are standard blueprints reused across matter templates — they are composed by matter and are never deployed directly.

| Molecule | Atoms |
|---|---|
| `swa` | `s3` + `cloudfront` + `waf` |
| `db` | `rds` + `sg` |
| `lambda-svc` | `lambda` + `sg` |

---

### ◆ Matter — Level 03
> *The only user-facing level.*

**Matter is the sole entry point for every deployment.** Even a deployment that uses a single molecule is expressed as a matter. Users declare their molecule stack and config in `composition.json`; the `eif` renderer produces ready-to-apply HCL via a Jinja2 template.

```json
{
  "matter": "three-tier-app",
  "aws_region": "us-east-1",
  "molecules": [
    {
      "name": "swa",
      "source": "../../molecules/swa",
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
├── eif.py                          # Jinja2 → HCL renderer CLI
├── pyproject.toml                  # Python project (uv / hatchling)
│
├── atoms/                          # Atomic AWS services (plain HCL)
│   ├── networking/
│   │   └── cloudfront/             # main.tf · variables.tf · outputs.tf
│   ├── storage/
│   │   └── s3/
│   └── security/
│       └── waf/
│
├── molecules/                      # Self-contained blueprints
│   └── swa/                        # Static Web App: s3 + cloudfront + waf
│
└── matter/                         # Complete applications
    └── three-tier-app/
        ├── composition.json        # user-edited config (input)
        ├── main.tf.j2              # Jinja2 template
        └── main.tf                 # rendered output — do not edit by hand
```

---

## ◐ Renderer

Matter templates are rendered by `eif.py` — a thin Python CLI built on [Jinja2](https://jinja.palletsprojects.com/). Users declare their molecule stack and config in `composition.json`; the renderer produces valid HCL.

### How it works

```
composition.json  ──┐
                    ├──▶  eif render  ──▶  main.tf
main.tf.j2        ──┘
```

### Template example

```jinja
{% for mol in molecules %}
module "{{ mol.name }}" {
  source = "{{ mol.source }}"

  {% for key, value in mol.config.items() %}
  {% if value is sameas true %}
  {{ key }} = true
  {% elif value is string %}
  {{ key }} = "{{ value }}"
  {% else %}
  {{ key }} = {{ value }}
  {% endif %}
  {% endfor %}
}
{% endfor %}
```

---

## ▶ Usage

### Prerequisites

- Python `>= 3.11` with [uv](https://docs.astral.sh/uv/)
- Terraform `>= 1.5`
- AWS CLI configured with appropriate credentials

### Install

```bash
uv sync
```

### Render and deploy

```bash
# render composition.json → main.tf
uv run eif matter/three-tier-app

# deploy
terraform -chdir=matter/three-tier-app init
terraform -chdir=matter/three-tier-app apply
```

Matter is the only deployment entry point. Atoms and molecules are internal — use them as building blocks when authoring new matter templates, but never deploy them directly.

---

## ◌ Roadmap

- [x] Atom library: `s3`, `cloudfront`, `waf`, `lambda`, `rds`, `sg`
- [x] Molecule library: `swa`, `db`, `lambda-svc`
- [x] Matter template: `three-tier-app` (`swa` + `db` + `lambda-svc`)
- [x] Jinja2 → HCL renderer (`eif.py`)
- [ ] Atom library: compute (`ecs`), networking (`api-gateway`)
- [ ] Matter template: `serverless-api`
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
