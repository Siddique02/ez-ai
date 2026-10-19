from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, Query
from pathlib import Path
from uuid import uuid4
from sqlalchemy.orm import Session
from app.models.takeoff import TakeoffItem, TakeoffJob
from app.core.config import settings
from app.core.database import get_db
from app.core.tracing import propagate_attributes
from app.schemas.estimate import EstimateResponse
from app.schemas.takeoff import (
    TakeoffAnalysisResponse,
    TakeoffItemCreate,
    TakeoffItemUpdate,
    TakeoffResponse,
    TakeoffItemResponse,
)
from app.schemas.matching import DetectedMatchItem, ProductMatchingResponse
from app.tasks.takeoff_tasks import analyze_takeoff_task
from app.services.catalog_service import catalog_service, CatalogServiceError
from app.services.product_matching_service import (
    match_products,
    ProductMatchingServiceError,
)
from app.services.estimate_service import (
    EstimateJobNotFoundError,
    EstimateNotReadyError,
    EstimateServiceError,
    create_or_replace_estimate,
    find_estimate_prerequisite_issues,
    get_estimate_response,
)
from app.services.matching_persistence_service import (
    MatchingStateChangedError,
    replace_product_matches,
)
from app.services.takeoff_edit_service import (
    QuantityConflictError,
    TakeoffEditError,
    TakeoffItemNotFoundError,
    TakeoffNotEditableError,
    create_item,
    delete_item,
    update_item,
)


router = APIRouter(
    prefix="/takeoff",
    tags=["Takeoff"]
)


UPLOAD_DIR = Path("uploads/takeoffs")
UPLOAD_DIR.mkdir(
    parents=True,
    exist_ok=True
)

_UPLOAD_EXTENSIONS = {
    "application/pdf": {".pdf"},
    "image/png": {".png"},
    "image/jpeg": {".jpg", ".jpeg"},
}
_UPLOAD_CHUNK_SIZE = 1024 * 1024


@router.post("/upload")
async def upload_blueprint(
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    if file.content_type not in settings.allowed_file_types:
        raise HTTPException(
            status_code=400,
            detail="Only PDF, PNG and JPG files allowed"
        )

    original_name = Path(file.filename or "").name
    extension = Path(original_name).suffix.lower()
    allowed_extensions = _UPLOAD_EXTENSIONS.get(file.content_type, set())
    if not original_name or extension not in allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail="The filename extension does not match the uploaded file type",
        )

    file_path = UPLOAD_DIR / f"{uuid4().hex}{extension}"
    maximum_bytes = settings.max_upload_size_mb * 1024 * 1024
    bytes_written = 0

    try:
        with open(file_path, "wb") as buffer:
            while chunk := await file.read(_UPLOAD_CHUNK_SIZE):
                bytes_written += len(chunk)
                if bytes_written > maximum_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=(
                            f"File exceeds the {settings.max_upload_size_mb} MB "
                            "upload limit"
                        ),
                    )
                buffer.write(chunk)
    except HTTPException:
        file_path.unlink(missing_ok=True)
        raise
    except OSError as exc:
        file_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=500,
            detail="The uploaded file could not be saved",
        ) from exc
    finally:
        await file.close()

    job = TakeoffJob(
        file_name=original_name,
        file_path=str(file_path),
        status="uploaded"
    )

    try:
        db.add(job)
        db.commit()
        db.refresh(job)
    except Exception:
        db.rollback()
        file_path.unlink(missing_ok=True)
        raise


    return {
        "takeoff_id": job.id,
        "file_name": job.file_name,
        "status": job.status
    }

@router.get("/{job_id}", response_model=TakeoffResponse)
def get_takeoff(job_id: int, db: Session = Depends(get_db)):

    job = db.query(TakeoffJob).filter(
        TakeoffJob.id == job_id
    ).first()


    if not job:
        raise HTTPException(
            status_code=404,
            detail="Takeoff not found"
        )


    return {
        "id": job.id,
        "file_name": job.file_name,
        "status": job.status
    }

@router.post(
    "/{job_id}/analyze",
    response_model=TakeoffAnalysisResponse,
)
def analyze_takeoff(
    job_id: int,
    force: bool = Query(
        default=False,
        description="Rerun AI analysis and replace the existing items",
    ),
    db: Session = Depends(get_db),
):

    job = db.query(TakeoffJob).filter(
        TakeoffJob.id == job_id
    ).first()


    if not job:
        raise HTTPException(
            status_code=404,
            detail="Takeoff job not found"
        )


    existing_items_count = (
        db.query(TakeoffItem)
        .filter(TakeoffItem.job_id == job_id)
        .count()
    )

    if job.status == "completed" and not force:
        return TakeoffAnalysisResponse(
            job_id=job.id,
            status="completed",
            items_found=existing_items_count,
            reused=True,
        )

    if job.status == "processing":
        raise HTTPException(
            status_code=409,
            detail="Takeoff analysis is already processing",
        )

    previous_status = job.status

    claimed = (
        db.query(TakeoffJob)
        .filter(
            TakeoffJob.id == job_id,
            TakeoffJob.status != "processing",
        )
        .update(
            {TakeoffJob.status: "processing"},
            synchronize_session=False,
        )
    )
    db.commit()

    if claimed == 0:
        raise HTTPException(
            status_code=409,
            detail="Takeoff analysis is already processing",
        )

    # The job is now claimed ("processing"). Hand the slow work to a worker via
    # Redis and return at once; the client polls GET /takeoff/{id} for status.
    try:
        analyze_takeoff_task.delay(
            job_id,
            previous_status,
            existing_items_count > 0,
        )
    except Exception as exc:
        # The queue is unreachable; release the claim so the job can be retried
        # instead of being stuck in "processing".
        (
            db.query(TakeoffJob)
            .filter(TakeoffJob.id == job_id)
            .update(
                {TakeoffJob.status: previous_status or "uploaded"},
                synchronize_session=False,
            )
        )
        db.commit()
        raise HTTPException(
            status_code=503,
            detail="Could not queue analysis; try again shortly",
        ) from exc

    return TakeoffAnalysisResponse(
        job_id=job_id,
        status="processing",
        items_found=existing_items_count,
        reused=False,
    )

@router.get(
    "/{job_id}/items",
    response_model=list[TakeoffItemResponse]
)
def get_takeoff_items(
    job_id: int,
    db: Session = Depends(get_db)
):

    items = (
        db.query(TakeoffItem)
        .filter(
            TakeoffItem.job_id == job_id
        )
        .all()
    )

    return items


def _edit_http_error(exc: TakeoffEditError) -> HTTPException:
    if isinstance(exc, TakeoffItemNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, TakeoffNotEditableError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, QuantityConflictError):
        return HTTPException(
            status_code=422,
            detail={
                "message": str(exc),
                "calculated_quantity": exc.calculated,
            },
        )
    return HTTPException(status_code=500, detail="The item could not be saved")


@router.post(
    "/{job_id}/items",
    response_model=TakeoffItemResponse,
    status_code=201,
)
def create_takeoff_item(
    job_id: int,
    payload: TakeoffItemCreate,
    db: Session = Depends(get_db),
):
    try:
        return create_item(db, job_id, payload)
    except TakeoffEditError as exc:
        db.rollback()
        raise _edit_http_error(exc) from exc
    except Exception:
        db.rollback()
        raise


@router.patch(
    "/{job_id}/items/{item_id}",
    response_model=TakeoffItemResponse,
)
def update_takeoff_item(
    job_id: int,
    item_id: int,
    payload: TakeoffItemUpdate,
    db: Session = Depends(get_db),
):
    try:
        return update_item(db, job_id, item_id, payload)
    except TakeoffEditError as exc:
        db.rollback()
        raise _edit_http_error(exc) from exc
    except Exception:
        db.rollback()
        raise


@router.delete(
    "/{job_id}/items/{item_id}",
    status_code=204,
)
def delete_takeoff_item(
    job_id: int,
    item_id: int,
    db: Session = Depends(get_db),
):
    try:
        delete_item(db, job_id, item_id)
    except TakeoffEditError as exc:
        db.rollback()
        raise _edit_http_error(exc) from exc
    except Exception:
        db.rollback()
        raise


@router.post(
    "/{job_id}/match",
    response_model=ProductMatchingResponse,
)
def match_takeoff_items(
    job_id: int,
    db: Session = Depends(get_db),
):
    job = db.query(TakeoffJob).filter(
        TakeoffJob.id == job_id
    ).first()

    if not job:
        raise HTTPException(
            status_code=404,
            detail="Takeoff job not found",
        )

    items = (
        db.query(TakeoffItem)
        .filter(TakeoffItem.job_id == job_id)
        .all()
    )
    if not items:
        raise HTTPException(
            status_code=409,
            detail="Analyze the takeoff before matching products",
        )

    detected_items = [
        DetectedMatchItem.model_validate(item, from_attributes=True)
        for item in items
    ]
    expected_item_ids = [item.id for item in detected_items if item.id is not None]

    # Catalog and OpenAI calls are external I/O. End the read transaction before
    # making them, then verify the item IDs again while saving the results.
    db.rollback()

    try:
        catalog_products = catalog_service.get_products()
    except CatalogServiceError as exc:
        raise HTTPException(
            status_code=502,
            detail=str(exc),
        ) from exc

    try:
        with propagate_attributes(
            trace_name="product-matching",
            metadata={"job_id": str(job_id)},
        ):
            matches = match_products(detected_items, catalog_products)
    except ProductMatchingServiceError as exc:
        raise HTTPException(
            status_code=502,
            detail=str(exc),
        ) from exc

    try:
        replace_product_matches(
            db,
            job_id,
            expected_item_ids,
            matches,
        )
    except MatchingStateChangedError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail=str(exc),
        ) from exc
    except Exception:
        db.rollback()
        raise

    return ProductMatchingResponse(
        job_id=job_id,
        matches=matches,
    )


@router.post("/{job_id}/estimate", response_model=EstimateResponse)
def create_estimate(
    job_id: int,
    force: bool = Query(False),
    db: Session = Depends(get_db),
):
    existing = get_estimate_response(db, job_id)
    if existing is not None and not force:
        return existing

    job = db.query(TakeoffJob).filter(TakeoffJob.id == job_id).first()
    if job is None:
        raise HTTPException(
            status_code=404,
            detail="Takeoff job not found",
        )
    if job.status != "completed":
        raise HTTPException(
            status_code=409,
            detail="Takeoff analysis must be completed first",
        )

    prerequisite_issues = find_estimate_prerequisite_issues(db, job_id)
    if prerequisite_issues:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "The estimate has items that require review",
                "items": [issue.to_dict() for issue in prerequisite_issues],
            },
        )

    # Do not hold a database transaction open during the PHP API request.
    db.rollback()
    try:
        catalog_products = catalog_service.get_products()
    except CatalogServiceError as exc:
        raise HTTPException(
            status_code=502,
            detail=str(exc),
        ) from exc

    try:
        return create_or_replace_estimate(
            db,
            job_id,
            catalog_products,
            force=force,
        )
    except EstimateJobNotFoundError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except EstimateNotReadyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail={
                "message": str(exc),
                "items": [issue.to_dict() for issue in exc.issues],
            },
        ) from exc
    except EstimateServiceError as exc:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="The estimate could not be created",
        ) from exc
    except Exception:
        db.rollback()
        raise

@router.get("/{job_id}/estimate", response_model=EstimateResponse)
def get_estimate(
    job_id: int,
    db: Session = Depends(get_db),
):
    job = db.query(TakeoffJob.id).filter(TakeoffJob.id == job_id).first()
    if job is None:
        raise HTTPException(
            status_code=404,
            detail="Takeoff job not found",
        )

    estimate = get_estimate_response(db, job_id)
    if estimate is None:
        raise HTTPException(
            status_code=404,
            detail="Estimate not found",
        )
    return estimate
