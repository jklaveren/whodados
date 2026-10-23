# Cartao 3a — IaC do backend + banco (WhoDados).
#
# Espelha o deploy de producao (render.yaml: API FastAPI/uvicorn + Postgres
# via Supabase) para ambiente local reproduzivel com Docker. O Render nao tem
# provider oficial, entao este TF e a prova versionada da topologia:
# backend (uvicorn) + postgres (espelho local do schema Supabase).
#
# Uso:
#   terraform -chdir=infra init
#   terraform -chdir=infra validate
#   terraform -chdir=infra plan

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    docker = {
      source  = "kreuzwerker/docker"
      version = "~> 3.0"
    }
  }
}

provider "docker" {}

# ---------------------------------------------------------------- variaveis
variable "postgres_user" {
  type        = string
  default     = "whodados_user"
  description = "Usuario do Postgres local (producao usa Supabase via DATABASE_URL)"
}

variable "postgres_password" {
  type        = string
  default     = "whodados_dev_only"
  sensitive   = true
  description = "Senha local. Producao: segredo no Render/Supabase, nunca aqui."
}

variable "postgres_db" {
  type    = string
  default = "whodados"
}

variable "api_port" {
  type    = number
  default = 8000
}

variable "backend_image" {
  type        = string
  default     = "whodados-backend:local"
  description = "Imagem do backend (build local do Dockerfile do backend)"
}

# ----------------------------------------------------------------- recursos
resource "docker_network" "whodados" {
  name = "whodados-net"
}

resource "docker_volume" "pgdata" {
  name = "whodados-pgdata"
}

resource "docker_image" "postgres" {
  name = "postgres:16-alpine"
}

resource "docker_container" "db" {
  name  = "whodados-db"
  image = docker_image.postgres.image_id

  env = [
    "POSTGRES_USER=${var.postgres_user}",
    "POSTGRES_PASSWORD=${var.postgres_password}",
    "POSTGRES_DB=${var.postgres_db}",
  ]

  volumes {
    volume_name    = docker_volume.pgdata.name
    container_path = "/var/lib/postgresql/data"
  }

  networks_advanced {
    name = docker_network.whodados.name
  }

  healthcheck {
    test     = ["CMD-SHELL", "pg_isready -U ${var.postgres_user} -d ${var.postgres_db}"]
    interval = "10s"
    timeout  = "5s"
    retries  = 5
  }
}

resource "docker_container" "api" {
  name  = "whodados-api"
  image = var.backend_image

  env = [
    "DATABASE_URL=postgresql://${var.postgres_user}:${var.postgres_password}@whodados-db:5432/${var.postgres_db}",
    "DATA_SOURCE=database",
  ]

  ports {
    internal = 8000
    external = var.api_port
  }

  networks_advanced {
    name = docker_network.whodados.name
  }

  depends_on = [docker_container.db]
}

output "api_url" {
  value = "http://localhost:${var.api_port}"
}
