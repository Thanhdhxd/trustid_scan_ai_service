import sys
with open('e:/TTTN/trustid-scan-ai-service/app.py', 'rb') as f:
    data = f.read()
data = data.replace(b'\x00', b'')
with open('e:/TTTN/trustid-scan-ai-service/app.py', 'wb') as f:
    f.write(data)
print("done")
