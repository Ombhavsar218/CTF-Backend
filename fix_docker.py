path = r'E:\Flag-hunt\ctf-platform-be\manager\app\runtime\docker_adapter.py'
with open(path,'rb') as f:
    b = f.read()
i = 0
while i < len(b) and b[i] in (32,9,10,13):
    i += 1
with open(path,'wb') as f:
    f.write(b[i:])
print('done')
