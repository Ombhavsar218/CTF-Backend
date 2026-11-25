s = open('broker/firewall_controller_service/ownership_store.py').read()
idx = s.find("controller_audit")
start = s.rfind('\n', 0, idx) + 1
end = s.find('\n', idx)
print(repr(s[start:end]))
# look further
# find where it might end
idx2 = s.find('controller_evidence')
start2 = s.rfind('\n', 0, idx2) + 1
end2 = s.find('\n', idx2)
print('---')
print(repr(s[start2:end2]))
