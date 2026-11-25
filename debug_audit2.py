s = open('broker/firewall_controller_service/ownership_store.py').read()
# look around line 81
# find "controller_audit" then look ahead
idx = s.find("controller_audit")
# find next occurrence of execute or just look ahead ~200 chars
chunk = s[idx:idx+400]
print(repr(chunk))
