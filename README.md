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
                              ↓
                         Celery Worker
                              ↓
                    SVD Model → AWS S3
```
