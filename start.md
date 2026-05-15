# Full Startup Guide for CloudAI

This is the complete process to run your Django + React + Celery + Redis project from scratch.

---

# 1. Start Docker Desktop

Open:

[Docker Desktop](https://www.docker.com/products/docker-desktop/?utm_source=chatgpt.com)

Wait until it says Docker is running.

---

# 2. Start Redis container

From your backend folder:

```bash id="f2m8qa"
docker run -d -p 6379:6379 redis
```

Verify:

```bash id="n7v1kc"
docker ps
```

You should see a Redis container running.

---

# 3. Open backend terminal

Go to backend project:

```bash id="x4t9yb"
cd backend/aicloudproject
```

---

# 4. Activate virtual environment

Git Bash:

```bash id="q8p3re"
source .venv/Scripts/activate
```

Windows CMD:

```bash id="u5m7lw"
.venv\Scripts\activate
```

---

# 5. Install dependencies (first time only)

```bash id="b1c6zd"
pip install -r requirements.txt
```

If Celery missing:

```bash id="w3r9kn"
pip install celery redis
```

---

# 6. Verify `.env`

Make sure these exist:

```env id="j9f2qc"
DJANGO_SECRET_KEY=
GOOGLE_OAUTH2_CLIENT_ID=
GOOGLE_OAUTH2_CLIENT_SECRET=
LLM_API_KEY=
CELERY_BROKER_URL=redis://localhost:6379/0
```

---

# 7. Run database migrations

```bash id="v6n4pe"
python manage.py migrate
```

---

# 8. Start Django server

Terminal #1:

```bash id="s2k8mx"
python manage.py runserver
```

Server should start on:

```text id="r5t1va"
http://localhost:8000
```

---

# 9. Start Celery worker

Open Terminal #2:

```bash id="c7y4qd"
cd backend/aicloudproject
source .venv/Scripts/activate
```

Run:

```bash id="h8u2wr"
python -m celery -A aicloudproject worker -l info --pool=solo
```

You should see:

```text id="k4e7zb"
Connected to redis://localhost:6379/0
celery@... ready.
```

---

# 10. Start Celery Beat (scheduled jobs)

Open Terminal #3:

```bash id="d1m6xt"
cd backend/aicloudproject
source .venv/Scripts/activate
```

Run:

```bash id="p9r3vk"
python -m celery -A aicloudproject beat -l info
```

This runs:

* periodic email sync,
* daily digests,
* preference refresh tasks.

---

# 11. Start frontend

Open Terminal #4:

```bash id="g3x8tn"
cd frontend1
```

Install packages (first time only):

```bash id="m5v1qc"
npm install
```

Run frontend:

```bash id="y7k2re"
npm run dev
```

Usually starts on:

```text id="u4n9wb"
http://localhost:5173
```

---

# 12. Test application

Now test:

## Backend API

Visit:

```text id="e8r5cm"
http://localhost:8000/api/
```

---

## Frontend

Visit:

```text id="z1q7pd"
http://localhost:5173
```

---

# 13. Test Gmail OAuth

Flow:

1. Login/register
2. Connect Gmail
3. Google consent screen
4. Redirect back
5. Account stored in DB
6. Trigger sync
7. Watch Celery logs classify emails

---

# Daily development workflow

Every time you reboot your PC:

| Step                  | Needed |
| --------------------- | ------ |
| Start Docker          | ✅      |
| Start Redis container | ✅      |
| Activate `.venv`      | ✅      |
| Start Django          | ✅      |
| Start Celery worker   | ✅      |
| Start Celery Beat     | ✅      |
| Start React frontend  | ✅      |

---

# Useful commands

## Stop Redis container

```bash id="t6w2yk"
docker stop <container_id>
```

---

## Remove Redis container

```bash id="v3n8qe"
docker rm <container_id>
```

---

## See Celery tasks executing

Watch worker logs in Terminal #2.

---

# Later improvement (recommended)

You should eventually create:

```text id="l2m9ra"
docker-compose.yml
```

so you can start everything with:

```bash id="q7v4ep"
docker compose up
```

instead of manually opening multiple terminals.

That’s your next major infrastructure upgrade.
