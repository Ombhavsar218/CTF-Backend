with open('out2.txt','rb') as f:
    data = f.read()
try:
    s = data.decode('utf-8')
except:
    try:
        s = data.decode('utf-16')
    except:
        s = str(data)
if 'Invalid lifecycle' in s:
    idx = s.find('Invalid lifecycle')
    print(s[max(0,idx-80):idx+120])
elif 'PermissionError' in s:
    idx = s.find('PermissionError')
    print(s[max(0,idx-80):idx+120])
else:
    print(s[-500:])
