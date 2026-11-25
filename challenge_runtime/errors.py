"""Bounded error types for the challenge Docker runtime."""


class RuntimeErrorBase(Exception):
    code = 'RUNTIME_ERROR'

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


class DockerUnavailable(RuntimeErrorBase):
    code = 'DOCKER_UNAVAILABLE'


class ImageUnavailable(RuntimeErrorBase):
    code = 'IMAGE_UNAVAILABLE'


class ContainerLaunchFailed(RuntimeErrorBase):
    code = 'CONTAINER_LAUNCH_FAILED'


class ContainerInspectionFailed(RuntimeErrorBase):
    code = 'CONTAINER_INSPECTION_FAILED'


class ContainerCleanupFailed(RuntimeErrorBase):
    code = 'CONTAINER_CLEANUP_FAILED'


class ExecSessionError(RuntimeErrorBase):
    code = 'EXEC_SESSION_ERROR'


class ExecStreamClosed(ExecSessionError):
    code = 'EXEC_STREAM_CLOSED'


class ExecResizeFailed(ExecSessionError):
    code = 'EXEC_RESIZE_FAILED'


class ExecInspectionFailed(ExecSessionError):
    code = 'EXEC_INSPECTION_FAILED'
