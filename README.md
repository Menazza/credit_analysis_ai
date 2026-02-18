# Credit Analysis AI — Bank-Grade Corporate Credit Review Platform

A full-stack platform for corporate credit analysis: document ingestion, financial extraction, canonical mapping, deterministic metrics, facility/covenant analysis, rating engine, and audit-ready credit review packs.

## Architecture Overview

- **Web App (Next.js)**: Upload docs, view extracted FS/notes, fix mappings, run review jobs, generate packs, approvals
- **API (FastAPI)**: Auth, RBAC, portfolio/company/document/job/report endpoints
- **Workers (Celery)**: Ingest, layout, extraction, mapping, validation, normalization, financial engine, rating, report generation
- **Storage**: Postgres (metadata + structured), Object storage (PDFs, exports), Redis (queues, cache)
- **LLM**: Extraction/mapping/classification only (strict JSON, cached)

## Quick Start

### Prerequisites

- **Python 3.11** recommended (3.12 ok; 3.13 may require building PyMuPDF from source on Windows). Node 20+, Docker (optional)
- Postgres 15+, Redis 7+
- MinIO or S3-compatible storage (for document uploads)

### 1. Database and storage

Create a Postgres database and (optionally) start Redis and MinIO:

```bash
# Option A: Docker for Postgres + Redis + MinIO
docker-compose up -d postgres redis minio

# Option B: Use existing Postgres; set DATABASE_URL in backend/.env
```

### 2. Backend

```bash
cd backend
# Windows: use Python 3.11 for PyMuPDF wheels (no compiler needed)
py -3.11 -m venv venv311
venv311\Scripts\activate
# Or: python -m venv .venv && .venv\Scripts\activate
pip install --upgrade pip
pip install -r requirements.txt
# .env in project root is loaded automatically
alembic upgrade head
python -m scripts.seed    # creates default tenant, user analyst@bank.com / password, sample company
uvicorn app.main:app --reload
```

### 3. Workers (optional, for ingest pipeline)

```bash
cd backend
celery -A app.worker.celery_app worker -l info
# celery -A app.worker.celery_app beat -l info   # for scheduled tasks
```

### 4. Frontend

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:3000. Log in with **analyst@bank.com** / **password**.

### Docker (all services)

```bash
docker-compose up -d
```

## Core User Journeys

1. **Annual credit review**: Load last review → upload AFS/MA/debt schedule/covenant cert → refresh extraction → recompute metrics → generate memo + pack
2. **New facility / increase**: Full onboarding, extract AFS + facility terms, model repayment capacity, security evaluation, recommendation + term sheet
3. **Ongoing monitoring**: Monthly/quarterly uploads, covenant tracking, triggers, watchlist

## Data Flow

Upload → Ingest (tokens, layout) → Statement extraction → Units/scale → Notes parse → Canonical mapping → Validation → Normalization → Financial engine → Rating → Pack generation → Approval

Every number is traceable to evidence (page, bbox, source file).

## License

Proprietary.
