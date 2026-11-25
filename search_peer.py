import os
for root, dirs, files in os.walk('broker/tests'):
    for f in files:
        if f.endswith('.py'):
            path = os.path.join(root,f)
            try:
                with open(path) as fh:
                    for i,line in enumerate(fh):
                        if 'peer_uid' in line:
                            print(path+':'+str(i+1)+':'+line)
                            break
            except:
                pass
