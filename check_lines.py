with open(r'broker\firewall_controller_service\ownership_store.py','rb') as f:
    data=f.read()
lines=data.split(b'\n')
if len(lines)>71:
    print(repr(lines[71]))
