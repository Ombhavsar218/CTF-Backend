s = open('broker/firewall_controller_service/ownership_store.py').read()
idx = s.find("store_evidence")
# look around
idx2 = s.find("INSERT INTO controller_evidence", idx)
chunk = s[idx2:idx2+200]
print(repr(chunk))
