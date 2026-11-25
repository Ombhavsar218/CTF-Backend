from fastapi import APIRouter, Depends, HTTPException, status

from . import catalog
from .auth import require_manager_auth
from .config import settings
from .schemas import (
    CatalogEntryResponse,
    CatalogResponse,
    CleanupRequest,
    HealthResponse,
    InspectRequest,
    ProvisionRequest,
    StopRequest,
)

router = APIRouter(prefix='/manager/v1')


@router.get('/health', response_model=HealthResponse)
async def health():
    return HealthResponse(status='ok', version=settings.app_version)


@router.get('/catalog', response_model=CatalogResponse)
async def get_catalog(_auth=Depends(require_manager_auth)):
    entries = []
    for entry in catalog.CATALOG.values():
        entries.append(
            CatalogEntryResponse(
                id=entry.id,
                verified_runnable=entry.verified_runnable,
                has_digest=entry.digest_pinned,
                description=entry.description,
            )
        )
    return CatalogResponse(
        entries=entries,
        max_cpu_cores=catalog.MAX_CPU_CORES,
        max_memory_mb=catalog.MAX_MEMORY_MB,
        max_pid_limit=catalog.MAX_PID_LIMIT,
        max_lifetime_seconds=catalog.MAX_LIFETIME_SECONDS,
        network_egress_denied_by_default=True,
    )


@router.post('/provision')
async def provision(req: ProvisionRequest, _auth=Depends(require_manager_auth)):
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail='Runtime manager not available',
    )


@router.post('/instances/{instance_id}/inspect')
async def inspect(instance_id: int, req: InspectRequest, _auth=Depends(require_manager_auth)):
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail='Runtime manager not available',
    )


@router.post('/instances/{instance_id}/stop')
async def stop(instance_id: int, req: StopRequest, _auth=Depends(require_manager_auth)):
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail='Runtime manager not available',
    )


@router.post('/instances/{instance_id}/cleanup')
async def cleanup(instance_id: int, req: CleanupRequest, _auth=Depends(require_manager_auth)):
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail='Runtime manager not available',
    )
