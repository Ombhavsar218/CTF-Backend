path = 'broker/tests/test_firewall_controller_service_skeleton.py'
with open(path) as f:
    s = f.read()

s2 = s.replace('FirewallControllerService(allowed_uids={1000}, allowed_gids={1000})', '_svc()')
with open(path,'w') as f:
    f.write(s2)
