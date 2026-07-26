# 🎬 AI Text-to-Video Generation Platform

A full-stack platform to generate AI-powered videos from text prompts using **Stable Video Diffusion**.

## Tech Stack
| Layer | Technology |
|-------|-----------|
| Backend API | FastAPI + Python |
| Auth | JWT (OAuth2) |
| Task Queue | Celery + Redis |
| AI Model | Stable Video Diffusion (SVD) |
| Storage | AWS S3 |
| Database | PostgreSQL + SQLAlchemy |
| Frontend | React.js + Tailwind CSS |
| DevOps | Docker + Docker Compose |

## Features
- 🔐 JWT Authentication (Register/Login)
- ✍️ Text prompt → AI video generation
- ⚙️ Async processing via Celery workers
- ☁️ Video storage on AWS S3
- 📊 Real-time status polling
- 🗂️ Personal video library

## Quick Start

```bash
git clone [github.com](https://github.com/yourusername/ai-text-to-video)
cd ai-text-to-video
cp backend/.env.example backend/.env
# Fill in your AWS and DB credentials in .env
docker-compose up --build
```

- API: [localhost](http://localhost:8000)
- Docs: [localhost](http://localhost:8000/docs)
- Frontend: [localhost](http://localhost:5173)

## Architecture
```
User → React Frontend → FastAPI → PostgreSQL

### Docker (recommended)

1. Copy `backend/.env.example` to `backend/.env`.
2. Set a strong, unique `SECRET_KEY` in `backend/.env`.
3. From the project root, run:

```bash
docker compose up --build
```

Open the frontend at `http://localhost:5173`. The API health endpoint is `http://localhost:8000/health`.

### Without Docker

Start the backend with Python 3.11 or newer:

```bash
cd backend
python app/main.py
```

In another terminal, start the frontend:

```bash
cd frontend
npm install
npm run dev
```

## Demo flow

1. Register a new account with a password of at least eight characters.
2. Sign in and choose **Generate preview**.
3. Enter a title and a prompt of 10–1,000 characters.
4. Watch the job move to completed, then view it from the dashboard.

## Important security note

The password-reset screen is intentionally a request-only flow. A password is never changed based on an email address alone. To make it fully functional, add a verified, time-limited reset token and an email delivery provider.

## Resume-ready description

Built an AI text-to-video preview studio using React, Tailwind CSS, Python, and SQLite. Implemented token-based authentication, protected routes, validated generation jobs, asynchronous status polling, and a browser-rendered animated preview library
                              ↓
                         Celery Worker
                              ↓
                    SVD Model → AWS S3
```
