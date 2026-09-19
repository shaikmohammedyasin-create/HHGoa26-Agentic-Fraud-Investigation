from pathlib import Path
import re
import urllib.request
import json

def verify_assets():
    html = Path('frontend/index.html').read_text(encoding='utf-8')
    css_files = re.findall(r'<link[^>]+href=["\']([^"\']+)["\']', html)
    js_files = re.findall(r'<script[^>]+src=["\']([^"\']+)["\']', html)

    print('CSS references in HTML:', css_files)
    print('JS references in HTML:', js_files)

    for ref in css_files + js_files:
        if ref.startswith('http'):
            print(f'External: {ref}')
            continue
        local_p = Path('frontend') / ref.lstrip('/')
        exists = local_p.exists()
        url = 'http://127.0.0.1:8000/' + ref.lstrip('/')
        try:
            resp = urllib.request.urlopen(url)
            http_status = resp.status
            size = len(resp.read())
        except Exception as e:
            http_status = f'ERROR: {e}'
            size = 0
        print(f'Ref: {ref} -> Local file exists: {exists} | HTTP: {http_status} ({size} bytes)')

if __name__ == '__main__':
    verify_assets()
