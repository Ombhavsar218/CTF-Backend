from pydantic_settings import BaseSettings
import os


class BrokerSettings(BaseSettings):
    app_name: str = 'flaghunt-broker'
    app_version: str = '0.1.0'
    # Unix domain socket configuration
    broker_socket_path: str = '/run/flaghunt/broker.sock'
    broker_socket_dir: str = '/run/flaghunt'
    broker_socket_mode: int = 0o660
    # Authorized manager identity
    authorized_manager_uid: int = -1
    authorized_manager_gid: int = -1
    authorized_manager_user: str = 'flaghunt-mgr'
    broker_token: str = ''
    audit_enabled: bool = True
    # Persistent storage paths
    broker_db_path: str = os.path.normpath(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'broker.db'))
    broker_audit_db_path: str = os.path.normpath(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'broker_audit.db'))
    require_persistent_storage: bool = True

    class Config:
        env_file = '.env'
        env_prefix = 'BROKER_'
        extra = 'ignore'


settings = BrokerSettings()
