from fastapi import FastAPI

from clew.server.config import settings
from clew.server.routes import graph, policies, search, stats

app = FastAPI(title=settings.APP_NAME, version=settings.APP_VERSION)

app.include_router(search.router, prefix="/v1/search", tags=["Search"])
app.include_router(graph.router, prefix="/v1/graph", tags=["Graph"])
app.include_router(stats.router, prefix="/v1/stats", tags=["Stats"])
app.include_router(policies.router, prefix="/v1/policies", tags=["Policies"])


@app.get("/health")
async def health_check():
    return {"status": "ok", "version": settings.APP_VERSION}
