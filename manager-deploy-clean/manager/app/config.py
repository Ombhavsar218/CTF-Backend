from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = 'flaghunt-manager'
    app_version: str = '0.1.0'
    manager_host: str = '127.0.0.1'
    manager_port: int = 8081
    manager_token: str = ''

    class Config:
        env_file = '.env'
        env_prefix = ''
        extra = 'ignore'


settings = Settings()
