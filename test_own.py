from unittest.mock import MagicMock
from app.runtime import DockerRuntimeAdapter
from app.runtime.base import RuntimeNotFoundError, RuntimeNotOwnedError

client = MagicMock()
client.containers.get.side_effect = Exception('not found')
adapter = DockerRuntimeAdapter(docker_client=client)
try:
    c = adapter._get_container_object(client, 'nonexistent')
    print('got')
except RuntimeNotFoundError:
    print('nf')
except RuntimeNotOwnedError:
    print('no')
except Exception as e:
    print('other')
