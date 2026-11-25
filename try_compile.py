s = open('broker/firewall_controller_service/ownership_store.py').read()
try:
    compile(s, 'x.py', 'exec')
    print('ok')
except Exception as e:
    print(e)
