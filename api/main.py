from fastapi import FastAPI

from api.activity import router as activity_router
from api.screenshotApi import router as screenshot_router


app = FastAPI(
    title="Activity Tracker API",
    description="API for activity tracking and screenshots",
    version="1.0.0",
)


# Activity API
app.include_router(activity_router)

# Screenshot API
app.include_router(screenshot_router)


@app.get("/")
async def root():
    return {
        "success": True,
        "message": "Activity Tracker API is running",
    }


@app.get("/health")
async def health():
    return {
        "status": "healthy",
    }