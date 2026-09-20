import subprocess
import re
from pathlib import Path

tracked = subprocess.check_output(['git', 'ls-files'], text=True).splitlines()

# Search for typical secret patterns
pats = [
    re.compile(r'(?i)(password|secret|api_key|token)\s*[:=]\s*[\'"][a-zA-Z0-9_\-\.]{12,}[\'"]'),
    re.compile(r'ghp_[a-zA-Z0-9]{36}'),
    re.compile(r'AIza[0-9A-Za-z-_]{35}'),
    re.compile(r'sk-[a-zA-Z0-9]{32,}'),
]

findings = []
for rel in tracked:
    p = Path(rel)
    if not p.is_file() or p.name in ['.env', '.gitignore']:
        continue
    try:
        text = p.read_text(encoding='utf-8', errors='ignore')
    except Exception:
        continue
    for i, line in enumerate(text.splitlines(), 1):
        if any(w in line for w in ['***', 'MASKED', 'example', 'placeholder', '<your-', 'type[', 'Field(', 'environ.get']):
            continue
        for pat in pats:
            if pat.search(line):
                findings.append((rel, i))

print(f"Tracked files scanned: {len(tracked)}")
print(f"Findings count: {len(findings)}")
for rel, line_num in findings:
    print(f"FOUND: {rel} at line {line_num}")
if not findings:
    print("NOT FOUND: Zero hardcoded secrets in tracked files.")
