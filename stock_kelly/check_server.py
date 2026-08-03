import socket
import sys

# Check what's on port 5000
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
try:
    s.connect(('127.0.0.1', 5000))
    s.close()
    print('Port 5000 is OPEN')
    
    # Make a test request
    import requests
    r = requests.get('http://127.0.0.1:5000/api/status', timeout=5)
    print('Server status:', r.json())
except Exception as e:
    print(f'Port 5000 error: {e}')

# Also check if our modified code is being used
import requests
r = requests.get('http://127.0.0.1:5000/', timeout=5)
# Check if resetResults is in the served HTML
if 'resetResults' in r.text:
    print('GOOD: resetResults found in served HTML')
else:
    print('BAD: resetResults NOT found in served HTML - old version being served!')

if 'currentAbortController' in r.text:
    print('GOOD: currentAbortController found in served HTML')
else:
    print('BAD: currentAbortController NOT found')

if 'isAnalyzing' in r.text:
    print('GOOD: isAnalyzing found in served HTML')
else:
    print('BAD: isAnalyzing NOT found')