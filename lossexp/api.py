"""FastAPI app: a thin HTTP mapping over service.LossIndex.

The index is built once at startup from LOSSEXP_DATA_DIR (default: `data/` at
the repository root) and stored on app.state.index.
"""

import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

from lossexp.data import FILES
from lossexp.service import InvalidFilter, LossIndex, PortfolioNotFound, build_index

log = logging.getLogger(__name__)

DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
STATIC_INDEX = Path(__file__).resolve().parent / "static" / "index.html"


def data_dir_from_env() -> Path:
    return Path(os.environ.get("LOSSEXP_DATA_DIR") or DEFAULT_DATA_DIR)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    data_dir = data_dir_from_env()
    missing = [name for name in FILES if not (data_dir / name).is_file()]
    if missing:
        raise RuntimeError(
            f"data directory {data_dir} is missing {missing}: unzip the four CSV files there "
            "or point LOSSEXP_DATA_DIR at them (see README.md)."
        )
    started = time.perf_counter()
    app.state.index = build_index(data_dir)
    log.info("index built from %s in %.2f s", data_dir, time.perf_counter() - started)
    yield


app = FastAPI(title="Envira loss-experience service", lifespan=lifespan)


@app.exception_handler(PortfolioNotFound)
async def portfolio_not_found(request: Request, exc: PortfolioNotFound) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(InvalidFilter)
async def invalid_filter(request: Request, exc: InvalidFilter) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


def _index(request: Request) -> LossIndex:
    return request.app.state.index


# Declared before the {portfolio_id} route so "loss-experience" is not read as an id.
@app.get("/portfolios/loss-experience")
def compare_portfolios(
    request: Request,
    underwriting_year: int | None = None,
    region: str | None = None,
    asset_type: str | None = None,
) -> dict:
    """All portfolios ranked by loss ratio, with the same optional filters."""
    return _index(request).compare(underwriting_year=underwriting_year, region=region, asset_type=asset_type)


@app.get("/portfolios/{portfolio_id}/loss-experience")
def portfolio_loss_experience(
    request: Request,
    portfolio_id: str,
    underwriting_year: int | None = None,
    region: str | None = None,
    asset_type: str | None = None,
) -> dict:
    """Loss experience per peril for one portfolio, all figures in DKK."""
    return _index(request).portfolio(
        portfolio_id, underwriting_year=underwriting_year, region=region, asset_type=asset_type,
    )


@app.get("/data-quality")
def data_quality(request: Request) -> dict:
    """What was excluded, normalised or noted while loading, and why."""
    return _index(request).quality()


@app.get("/health")
def health(request: Request) -> dict:
    return {"status": "ok", **_index(request).summary()}


@app.get("/", include_in_schema=False)
def root():
    if STATIC_INDEX.is_file():
        return FileResponse(STATIC_INDEX)
    return {"service": app.title, "docs": "/docs", "portfolios": "/portfolios/loss-experience"}
