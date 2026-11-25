from fastapi import APIRouter, Depends, HTTPException, status

from . import catalog
from . import policy
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
        # Return only explicitly approved catalog entries
        rp = entry.resource_profile
        rp_dict = {
            "cpu_limit_cores": rp.cpu_limit_cores,
            "memory_limit_mb": rp.memory_limit_mb,
            "pid_limit": rp.pid_limit,
            "max_lifetime_seconds": rp.max_lifetime_seconds,
            "network_egress_denied": rp.network_egress_denied,
        }
        entries.append(
            CatalogEntryResponse(
                id=entry.id,
                verified_runnable=entry.verified_runnable,
                has_digest=entry.digest_pinned,
                description=entry.description,
                challenge_image_id=entry.challenge_image_id,
                display_name=entry.display_name,
                image_repository=entry.image_repository,
                image_digest=entry.image_digest,
                approved_container_port=entry.approved_container_port,
                resource_profile=rp_dict,
                max_lifetime_seconds=entry.max_lifetime_seconds,
                storage_policy=entry.storage_policy,
                network_policy=entry.network_policy,
                health_check_settings=entry.health_check_settings,
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
    # Validate via policy layer without creating containers
    try:
        entry = catalog.get_entry_by_id_or_challenge_id(req.catalog_id)
        if not entry:
            raise HTTPException(status_code=422, detail='Unknown catalog identifier')
        spec = policy.PolicyValidator.validate_provision_request(
            challenge_image_id=entry.challenge_image_id,
            duration_seconds=req.duration_seconds,
            resource_profile=req.resource_profile,
            container_port=req.container_port,
        )
        # Still return 503 as runtime provisioning is disabled
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail='Runtime manager not available',
        )
    except policy.PolicyValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except HTTPException:
        raise
    except Exception:
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
