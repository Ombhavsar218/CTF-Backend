from fastapi import APIRouter, Depends, HTTPException, Request, status
import uuid

from .auth import require_broker_auth
from .schemas import (
    CreateContainerRequest,
    StartContainerRequest,
    InspectContainerRequest,
    StopContainerRequest,
    RemoveContainerRequest,
    HealthCheckRequest,
)
from .policy import broker_policy, BrokerPolicyError
from .docker_adapter import BrokerDockerAdapter, BrokerDockerError, BrokerDockerNotOwnedError
from .dependencies import get_ownership_store, get_audit_logger, get_adapter
from .recovery import orphan_registry

router = APIRouter(prefix='/broker/v1')


def _request_id(request: Request, req) -> str:
    return getattr(request.state, 'request_id', None) or getattr(req, 'request_id', None) or str(uuid.uuid4())


def _safe_audit(audit, operation, details=None, request_id=None, idempotency_key=None,
                challenge_id=None, container_id=None, result='ok', error_category=None):
    if audit is None or not hasattr(audit, 'log'):
        return
    try:
        audit.log(operation, details or {}, request_id=request_id,
                  idempotency_key=idempotency_key, challenge_id=challenge_id,
                  container_id=container_id, result=result, error_category=error_category)
    except TypeError:
        # Store with the older/simple signature
        try:
            audit.log(operation, details or {})
        except Exception:
            pass
    except Exception:
        pass


@router.get('/health')
async def health(_auth=Depends(require_broker_auth)):
    return {"status": "ok", "version": "0.1.0"}


@router.post('/containers/create')
async def create_container(req: CreateContainerRequest, request: Request,
                           _auth=Depends(require_broker_auth),
                           adapter: BrokerDockerAdapter = Depends(get_adapter),
                           store=Depends(get_ownership_store),
                           audit=Depends(get_audit_logger)):
    request_id = _request_id(request, req)
    try:
        spec = broker_policy.validate_create_request(
            req.challenge_image_id,
            resource_profile=req.resource_profile,
            approved_container_port=req.approved_container_port,
        )
        spec.image_ref = f"{spec.image_repository}@{spec.image_digest}"
        try:
            result = adapter.create_container(spec, req.instance_id)
        except Exception:
            _safe_audit(audit, 'broker.container.create.failed', {'reason': 'adapter'},
                        request_id=request_id, challenge_id=req.challenge_image_id,
                        result='error', error_category='adapter')
            raise BrokerDockerError("Container creation failure")
        container_id = result.get('container_id')
        if not container_id:
            _safe_audit(audit, 'broker.container.create.failed', {},
                        request_id=request_id, challenge_id=req.challenge_image_id,
                        result='error', error_category='adapter')
            raise BrokerDockerError("Container creation failure")
        labels = {
            "flaghunt.manager.managed": "true",
            "flaghunt.manager.owner": "flaghunt-manager",
            "flaghunt.manager.instance_id": str(req.instance_id),
            "flaghunt.manager.challenge_image_id": req.challenge_image_id,
        }
        try:
            # Persist ownership. Only after this succeeds may creation be reported as successful.
            try:
                store.record_creation(container_id, req.instance_id, req.challenge_image_id,
                                      labels=labels, image_digest=getattr(spec, 'image_digest', ''),
                                      request_id=request_id)
            except TypeError:
                # Older/simpler store signature (in-memory test store)
                store.record_creation(container_id, req.instance_id, req.challenge_image_id,
                                      labels=labels)
        except Exception:
            # Docker created the container but ownership persistence failed.
            # Attempt compensating removal; never claim success without ownership.
            cleanup_ok = False
            try:
                adapter.remove_container(container_id, force=False)
                cleanup_ok = True
            except Exception:
                cleanup_ok = False
            if not cleanup_ok:
                try:
                    orphan_registry.mark_orphan(
                        container_id, req.instance_id, req.challenge_image_id,
                        reason='persistence_failed_cleanup_unconfirmed',
                        request_id=request_id,
                    )
                except Exception:
                    pass
            _safe_audit(audit, 'broker.container.create.recovery',
                        {'container_id': container_id, 'cleanup_confirmed': cleanup_ok},
                        request_id=request_id, challenge_id=req.challenge_image_id,
                        container_id=container_id, result='error', error_category='persistence')
            raise HTTPException(status_code=500, detail="Internal error")
        _safe_audit(audit, 'broker.container.create', {'container_id': container_id},
                    request_id=request_id, challenge_id=req.challenge_image_id,
                    container_id=container_id, result='ok')
        return {"container_id": container_id, "status": "created"}
    except BrokerPolicyError:
        _safe_audit(audit, 'broker.container.create.denied', {'reason': 'policy'},
                    request_id=request_id, result='denied', error_category='policy')
        raise HTTPException(status_code=422, detail="Invalid request")
    except BrokerDockerError:
        _safe_audit(audit, 'broker.container.create.error', {},
                    request_id=request_id, result='error', error_category='adapter')
        raise HTTPException(status_code=500, detail="Internal error")
    except HTTPException:
        raise
    except Exception:
        _safe_audit(audit, 'broker.container.create.error', {},
                    request_id=request_id, result='error', error_category='unknown')
        raise HTTPException(status_code=500, detail="Internal error")


@router.post('/containers/{container_id}/start')
async def start_container(container_id: str, req: StartContainerRequest, request: Request,
                          _auth=Depends(require_broker_auth),
                          adapter: BrokerDockerAdapter = Depends(get_adapter),
                          store=Depends(get_ownership_store),
                          audit=Depends(get_audit_logger)):
    request_id = _request_id(request, req)
    try:
        store.verify(container_id)
        adapter.start_container(container_id)
        _safe_audit(audit, 'broker.container.start', {'container_id': container_id},
                    request_id=request_id, container_id=container_id, result='ok')
        return {"status": "started"}
    except (PermissionError, BrokerDockerNotOwnedError):
        _safe_audit(audit, 'broker.container.start.denied', {'container_id': container_id},
                    request_id=request_id, container_id=container_id, result='denied', error_category='ownership')
        raise HTTPException(status_code=403, detail="Forbidden")
    except BrokerDockerError:
        _safe_audit(audit, 'broker.container.start.error', {'container_id': container_id},
                    request_id=request_id, container_id=container_id, result='error')
        raise HTTPException(status_code=500, detail="Internal error")
    except Exception:
        _safe_audit(audit, 'broker.container.start.error', {'container_id': container_id},
                    request_id=request_id, container_id=container_id, result='error')
        raise HTTPException(status_code=500, detail="Internal error")


@router.post('/containers/{container_id}/inspect')
async def inspect_container(container_id: str, req: InspectContainerRequest, request: Request,
                            _auth=Depends(require_broker_auth),
                            adapter: BrokerDockerAdapter = Depends(get_adapter),
                            store=Depends(get_ownership_store),
                            audit=Depends(get_audit_logger)):
    request_id = _request_id(request, req)
    try:
        store.verify(container_id)
        info = adapter.inspect_container(container_id)
        _safe_audit(audit, 'broker.container.inspect', {'container_id': container_id},
                    request_id=request_id, container_id=container_id, result='ok')
        labels = getattr(info, 'labels', {}) or {}
        return {"container_id": container_id, "status": getattr(info, 'status', 'unknown'),
                "owned": True, "labels": labels}
    except (PermissionError, BrokerDockerNotOwnedError):
        _safe_audit(audit, 'broker.container.inspect.denied', {'container_id': container_id},
                    request_id=request_id, container_id=container_id, result='denied', error_category='ownership')
        raise HTTPException(status_code=403, detail="Forbidden")
    except BrokerDockerError:
        _safe_audit(audit, 'broker.container.inspect.error', {'container_id': container_id},
                    request_id=request_id, container_id=container_id, result='error')
        raise HTTPException(status_code=500, detail="Internal error")
    except Exception:
        _safe_audit(audit, 'broker.container.inspect.error', {'container_id': container_id},
                    request_id=request_id, container_id=container_id, result='error')
        raise HTTPException(status_code=500, detail="Internal error")


@router.post('/containers/{container_id}/stop')
async def stop_container(container_id: str, req: StopContainerRequest, request: Request,
                         _auth=Depends(require_broker_auth),
                         adapter: BrokerDockerAdapter = Depends(get_adapter),
                         store=Depends(get_ownership_store),
                         audit=Depends(get_audit_logger)):
    request_id = _request_id(request, req)
    try:
        store.verify(container_id)
        adapter.stop_container(container_id, timeout=req.timeout)
        _safe_audit(audit, 'broker.container.stop', {'container_id': container_id},
                    request_id=request_id, container_id=container_id, result='ok')
        return {"status": "stopped"}
    except (PermissionError, BrokerDockerNotOwnedError):
        _safe_audit(audit, 'broker.container.stop.denied', {'container_id': container_id},
                    request_id=request_id, container_id=container_id, result='denied', error_category='ownership')
        raise HTTPException(status_code=403, detail="Forbidden")
    except BrokerDockerError:
        _safe_audit(audit, 'broker.container.stop.error', {'container_id': container_id},
                    request_id=request_id, container_id=container_id, result='error')
        raise HTTPException(status_code=500, detail="Internal error")
    except Exception:
        _safe_audit(audit, 'broker.container.stop.error', {'container_id': container_id},
                    request_id=request_id, container_id=container_id, result='error')
        raise HTTPException(status_code=500, detail="Internal error")


@router.post('/containers/{container_id}/remove')
async def remove_container(container_id: str, req: RemoveContainerRequest, request: Request,
                           _auth=Depends(require_broker_auth),
                           adapter: BrokerDockerAdapter = Depends(get_adapter),
                           store=Depends(get_ownership_store),
                           audit=Depends(get_audit_logger)):
    request_id = _request_id(request, req)
    try:
        # Idempotent: removing a container we never owned is a no-op success.
        try:
            known = store.exists(container_id)
        except Exception:
            known = False
        if not known:
            _safe_audit(audit, 'broker.container.remove', {'container_id': container_id},
                        request_id=request_id, container_id=container_id, result='ok')
            return {"status": "removed"}
        try:
            store.verify(container_id)
        except PermissionError:
            _safe_audit(audit, 'broker.container.remove.denied', {'container_id': container_id},
                        request_id=request_id, container_id=container_id, result='denied', error_category='ownership')
            raise HTTPException(status_code=403, detail="Forbidden")
        try:
            adapter.remove_container(container_id, force=req.force)
        except BrokerDockerNotOwnedError:
            _safe_audit(audit, 'broker.container.remove.denied', {'container_id': container_id},
                        request_id=request_id, container_id=container_id, result='denied', error_category='ownership')
            raise HTTPException(status_code=403, detail="Forbidden")
        except Exception:
            # Container removal could not be confirmed. Do not drop the ownership
            # record; mark the resource for reconciliation and fail closed.
            try:
                orphan_registry.mark_orphan(container_id, '', '', reason='removal_unconfirmed', request_id=request_id)
            except Exception:
                pass
            _safe_audit(audit, 'broker.container.remove.recovery', {'container_id': container_id},
                        request_id=request_id, container_id=container_id, result='error', error_category='cleanup')
            raise HTTPException(status_code=500, detail="Internal error")
        try:
            store.remove(container_id)
        except PermissionError:
            _safe_audit(audit, 'broker.container.remove.denied', {'container_id': container_id},
                        request_id=request_id, container_id=container_id, result='denied', error_category='ownership')
            raise HTTPException(status_code=403, detail="Forbidden")
        except Exception:
            pass
        _safe_audit(audit, 'broker.container.remove', {'container_id': container_id},
                    request_id=request_id, container_id=container_id, result='ok')
        return {"status": "removed"}
    except HTTPException:
        raise
    except Exception:
        _safe_audit(audit, 'broker.container.remove.error', {'container_id': container_id},
                    request_id=request_id, container_id=container_id, result='error')
        raise HTTPException(status_code=500, detail="Internal error")


@router.post('/containers/{container_id}/health')
async def health_check_container(container_id: str, req: HealthCheckRequest, request: Request,
                                  _auth=Depends(require_broker_auth),
                                  adapter: BrokerDockerAdapter = Depends(get_adapter),
                                  store=Depends(get_ownership_store),
                                  audit=Depends(get_audit_logger)):
    request_id = _request_id(request, req)
    try:
        store.verify(container_id)
        res = adapter.health_check_container(container_id)
        _safe_audit(audit, 'broker.container.health', {'container_id': container_id},
                    request_id=request_id, container_id=container_id, result='ok')
        return res
    except (PermissionError, BrokerDockerNotOwnedError):
        _safe_audit(audit, 'broker.container.health.denied', {'container_id': container_id},
                    request_id=request_id, container_id=container_id, result='denied', error_category='ownership')
        raise HTTPException(status_code=403, detail="Forbidden")
    except BrokerDockerError:
        _safe_audit(audit, 'broker.container.health.error', {'container_id': container_id},
                    request_id=request_id, container_id=container_id, result='error')
        raise HTTPException(status_code=500, detail="Internal error")
    except Exception:
        _safe_audit(audit, 'broker.container.health.error', {'container_id': container_id},
                    request_id=request_id, container_id=container_id, result='error')
        raise HTTPException(status_code=500, detail="Internal error")
