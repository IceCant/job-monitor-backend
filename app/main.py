from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth, dashboard, firms, jobs, scraper
from app.database import init_db
from app.services.scheduler_service import scheduler_service

app = FastAPI(title="Job Monitor API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup():
    init_db()
    scheduler_service.start()


@app.on_event("shutdown")
def on_shutdown():
    scheduler_service.stop()


app.include_router(auth.router, prefix="/api/auth", tags=["Auth"])
app.include_router(jobs.router, prefix="/api/jobs", tags=["Jobs"])
app.include_router(firms.router, prefix="/api/firms", tags=["Firms"])
app.include_router(scraper.router, prefix="/api/scraper", tags=["Scraper"])
app.include_router(dashboard.router, prefix="/api/dashboard", tags=["Dashboard"])

@app.get("/health")
def health():
    return {"status":"ok"}
