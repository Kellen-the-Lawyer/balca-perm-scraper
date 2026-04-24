# Deploy Casebase to Google Cloud Run

This package builds the Vite frontend and FastAPI backend into one Cloud Run
container. The frontend is served from `perm-research/frontend/dist`, and all
API calls use relative `/api` routes.

## 1. Choose names

```bash
export PROJECT_ID="your-gcp-project"
export REGION="us-central1"
export SERVICE="casebase"
export REPO="casebase"
export IMAGE="$REGION-docker.pkg.dev/$PROJECT_ID/$REPO/$SERVICE:latest"
```

## 2. Enable services

```bash
gcloud services enable \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com \
  run.googleapis.com \
  secretmanager.googleapis.com \
  sqladmin.googleapis.com
```

## 3. Create an Artifact Registry repo

```bash
gcloud artifacts repositories create "$REPO" \
  --repository-format=docker \
  --location="$REGION"
```

## 4. Build and push the container

Cloud Build can build this image remotely, so local Docker is optional.

```bash
gcloud builds submit --tag "$IMAGE" .
```

## 5. Configure production environment

Create a Postgres database in Cloud SQL, migrate/import your local data, then
store the runtime database URL in Secret Manager.

```bash
printf '%s' 'postgresql://USER:PASSWORD@HOST:5432/DB_NAME' \
  | gcloud secrets create casebase-database-url --data-file=-
```

Optional secrets:

```bash
printf '%s' 'your-anthropic-key' \
  | gcloud secrets create anthropic-api-key --data-file=-
```

## 6. Deploy to Cloud Run

```bash
gcloud run deploy "$SERVICE" \
  --image "$IMAGE" \
  --region "$REGION" \
  --allow-unauthenticated \
  --port 8080 \
  --set-secrets DATABASE_URL=casebase-database-url:latest \
  --set-env-vars PDF_BASE_PATH=/tmp/pdfs
```

If you created `anthropic-api-key`, add:

```bash
--set-secrets ANTHROPIC_API_KEY=anthropic-api-key:latest
```

## Notes

- Cloud Run containers are stateless. Local PDF serving via `PDF_BASE_PATH`
  should be replaced with Cloud Storage before relying on stored PDFs in
  production.
- Use Cloud Run jobs for scraper/ingest/retry tasks after the web service is
  deployed.
- Keep `.env` files local. Runtime configuration should come from Cloud Run
  environment variables and Secret Manager.
