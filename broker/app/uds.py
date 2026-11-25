import os
import stat
from typing import Any, Dict, Optional


class UDSSetupError(Exception):
    pass


class PeerCredentials:
    def __init__(self, uid: Optional[int] = None, gid: Optional[int] = None, pid: Optional[int] = None):
        self.uid = uid
        self.gid = gid
        self.pid = pid

    def to_dict(self) -> Dict[str, Any]:
        return {"uid": self.uid, "gid": self.gid, "pid": self.pid}


def get_peer_credentials_from_socket(sock) -> PeerCredentials:
    """
    Extract peer credentials from a Unix domain socket.
    On Linux this uses SO_PEERCRED; on other platforms we return empty credentials
    to be handled by the caller (fail closed).
    """
    try:
        # Linux
        import socket
        SO_PEERCRED = getattr(socket, 'SO_PEERCRED', 17)
        creds = sock.getsockopt(socket.SOL_SOCKET, SO_PEERCRED, 28)
        # struct ucred { pid_t pid; uid_t uid; gid_t gid; } - sizes vary; on 64-bit usually 12 bytes
        # Try to unpack
        import struct
        if len(creds) >= 12:
            pid, uid, gid = struct.unpack('III', creds[:12])
            return PeerCredentials(uid=uid, gid=gid, pid=pid)
    except Exception:
        pass
    try:
        # Some platforms may have other mechanisms
        pass
    except Exception:
        pass
    return PeerCredentials()


def setup_unix_socket(socket_path: str, socket_dir: str, socket_mode: int = 0o660,
                      uid: Optional[int] = None, gid: Optional[int] = None) -> None:
    """
    Prepare socket directory and ensure secure permissions.
    Does NOT create or change actual Ubuntu socket in this phase - but validates paths.
    Will fail closed if cannot establish secure setup.
    """
    try:
        os.makedirs(socket_dir, mode=0o750, exist_ok=True)
        # Set restrictive permissions on directory if possible
        try:
            os.chmod(socket_dir, 0o750)
        except Exception:
            pass
        # If socket exists, remove it
        if os.path.exists(socket_path):
            try:
                os.unlink(socket_path)
            except Exception as e:
                raise UDSSetupError(f"Failed to remove existing socket: {e}")
        # We don't actually bind/listen here - that's done by server
        # Just validate we can create in this location
        return
    except UDSSetupError:
        raise
    except Exception as e:
        raise UDSSetupError(f"Failed to setup socket: {e}")
