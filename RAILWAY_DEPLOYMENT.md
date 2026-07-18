# Railway single FastAPI deployment manual

Last verified against Railway docs: 2026-07-18

This manual publishes the project as one Railway FastAPI service. The intended
shape is:

- Railway runs `main.py` as the API server.
- The same FastAPI app serves `index.html` at `/`.
- SQLite lives on a Railway Volume so sessions, logs, recognition jobs, and
  admin changes survive redeploys.
- Secrets are stored in Railway service variables, not in Git.

## 1. Before deployment

### Confirm the project is ready

Run these locally before pushing:

```powershell
.venv\Scripts\python.exe -m pytest
.venv\Scripts\python.exe -m uvicorn main:app --reload
```

Then check:

```powershell
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/meta/schema
```

### Make the app serve the frontend from FastAPI

Railway will run the FastAPI app, not GitHub Pages. To make one public Railway
URL serve both the UI and API, add a root route to `main.py`.

Add this import:

```python
from fastapi.responses import FileResponse
```

Add this route after the app/middleware setup:

```python
@app.get("/", include_in_schema=False)
def web_app() -> FileResponse:
    return FileResponse(Path(__file__).with_name("index.html"))
```

Then update the frontend API default in `index.html` so it calls the same
Railway origin by default:

```javascript
const API_BASE_URL =
  window.BOARDGAME_API_BASE_URL ||
  new URLSearchParams(location.search).get('apiBase') ||
  localStorage.getItem('boardgameApiBaseUrl') ||
  location.origin;
```

Local development still works if you open the frontend from the FastAPI server
at `http://127.0.0.1:8000/`.

### Make SQLite directory creation explicit

The production DB path will point at `/app/data/boardgame_backend.sqlite3`.
Railway creates the mounted directory, but it is still safer for startup to
ensure the parent directory exists before connecting:

```python
def startup() -> None:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    create_schema()
    seed_data()
```

Do not commit `.env`, `boardgame_backend.sqlite3`, or local log files.

## 2. Push to GitHub

The current repository target is:

```text
https://github.com/alexmonkey05/boardgame_tutorial
```

Commit and push the deployment-ready code:

```powershell
git status
git add main.py index.html RAILWAY_DEPLOYMENT.md
git commit -m "Prepare Railway deployment"
git push origin main
```

If you only add this manual and do not make the code changes above, Railway can
still run the API, but `/` will not show the web app.

## 3. Create the Railway service

1. Open Railway.
2. Create a new project.
3. Choose `Deploy from GitHub repo`.
4. Select `alexmonkey05/boardgame_tutorial`.
5. Deploy the `main` branch.

Railway can detect Python projects from `requirements.txt`, but set the start
command explicitly to avoid ambiguity:

```bash
uvicorn main:app --host 0.0.0.0 --port $PORT
```

Why this matters: Railway injects the `PORT` environment variable, and public
services must listen on `0.0.0.0:$PORT`.

## 4. Attach persistent SQLite storage

Create a Railway Volume and attach it to the FastAPI service.

Recommended mount path:

```text
/app/data
```

Then set this service variable:

```text
BOARDGAME_DB_PATH=/app/data/boardgame_backend.sqlite3
```

Notes:

- Railway application files live under `/app`, so `/app/data` is the natural
  mount path for app-owned data.
- Volumes are available at runtime, not during build time.
- With SQLite on a Volume, keep the service to one running instance. Do not
  enable horizontal replicas for this app until the DB is moved to Postgres.
- Enable Railway Volume backups after the first successful deployment.

## 5. Add service variables

In the Railway service, open the `Variables` tab and add:

```text
BOARDGAME_DB_PATH=/app/data/boardgame_backend.sqlite3
ADMIN_TOKEN=<strong-production-admin-token>
VISION_API_PROVIDER=nvidia
VISION_API_KEY=<your-provider-api-key>
VISION_API_ENDPOINT=<your-provider-endpoint>
VISION_MODEL=<your-model-name>
```

For a public demo without real image recognition, use:

```text
VISION_API_PROVIDER=mock
```

Keep `.env` local only. Railway variables are exposed to the build and runtime
environment, so the app can read them through `os.getenv(...)`.

## 6. Configure networking and healthcheck

In the Railway service settings:

1. Open `Networking`.
2. Generate a public domain.
3. Open the generated HTTPS URL.

Set the healthcheck path:

```text
/health
```

Railway uses the healthcheck during deployment to wait for an HTTP 200 before
switching traffic to the new deployment. Because this service uses a Volume,
expect a small amount of downtime during redeploys.

## 7. Validate the deployment

Replace `<railway-url>` with the generated domain:

```powershell
curl https://<railway-url>/health
curl https://<railway-url>/meta/schema
curl https://<railway-url>/games
curl https://<railway-url>/cafes/cafe-hongdae/games
```

Browser checks:

- `https://<railway-url>/` loads the mobile web app.
- `https://<railway-url>/docs` loads FastAPI Swagger docs.
- The home screen does not show an API connection failure.
- Recommendations load from the API.
- Image recognition works with `mock` or the configured Vision provider.

Useful recognition smoke test without uploading an image:

```powershell
curl -X POST "https://<railway-url>/recognitions?cafeId=cafe-hongdae&hint=splendor"
```

## 8. Production hardening checklist

Before sharing with real users:

- Replace `ADMIN_TOKEN=dev-admin-token` with a strong secret.
- Restrict CORS to the Railway/custom domain instead of `allow_origins=["*"]`;
  after generating the public domain, set
  `CORS_ALLOWED_ORIGINS=https://<railway-url>`.
- Keep `BOARDGAME_DB_PATH` on the mounted Volume path.
- Turn on Volume backups.
- Check Railway logs after image uploads and recommendation calls.
- Add a custom domain if the app will be used in a real cafe.
- Add rate limits or request-size controls if the URL is public.
- Plan a migration from SQLite to Postgres before multi-instance scaling.

## 9. Common problems

### Deployment succeeds but the app is unreachable

Check the start command. It must bind to Railway's injected port:

```bash
uvicorn main:app --host 0.0.0.0 --port $PORT
```

### `/` does not show the frontend

The FastAPI root route was not added, or `index.html` is not included in the
repository root. Add the `FileResponse` route from section 1.

### Data disappears after redeploy

The app is writing SQLite to the container filesystem instead of the Volume.
Confirm:

```text
BOARDGAME_DB_PATH=/app/data/boardgame_backend.sqlite3
```

Then check `/health`; the `database` field should point to `/app/data/...`.

### Image recognition always uses fallback

Check `/health`. The `imageRecognition` object should show the provider, API
key, endpoint, and model as configured. If any field is missing, add the
corresponding Railway variable and redeploy.

### Browser blocks API calls

Use one HTTPS Railway URL for both frontend and API. Avoid loading the frontend
from GitHub Pages while calling a plain `http://` backend, because browsers
block mixed-content requests.

## 10. Official references

- Railway FastAPI guide: https://docs.railway.com/guides/fastapi
- Railway start command docs: https://docs.railway.com/deployments/start-command
- Railway public networking and `PORT`: https://docs.railway.com/public-networking
- Railway application response troubleshooting: https://docs.railway.com/networking/troubleshooting/application-failed-to-respond
- Railway variables: https://docs.railway.com/variables
- Railway volumes: https://docs.railway.com/volumes
- Railway healthchecks: https://docs.railway.com/deployments/healthchecks
