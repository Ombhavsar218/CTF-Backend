from manager.app.runtime import DockerRuntimeAdapter
from unittest.mock import MagicMock
from manager.app.policy import ValidatedRuntimeSpec
spec = ValidatedRuntimeSpec('t','r','sha256:'+'a'*64,'r:latest','t',80,{},{},3600,'ephemeral','deny_all_egress',{},True,True)
try:
    a = DockerRuntimeAdapter(MagicMock())
    a.create_container(spec, instance_id='1')
    print('bad')
except Exception as e:
    print(type(e).__name__)
