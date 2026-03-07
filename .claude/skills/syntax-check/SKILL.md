---
description: Syntax check all Python files in TastyMechanics using ast.parse
disable-model-invocation: true
allowed-tools: Bash
---

Syntax check every Python file in the project:

```bash
python3 -c "
import ast, glob, sys
files = sorted(glob.glob('**/*.py', recursive=True))
errors = []
for f in files:
    try:
        ast.parse(open(f).read())
        print(f'OK  {f}')
    except SyntaxError as e:
        print(f'ERR {f}: {e}')
        errors.append(f)
print()
print(f'{len(files)} files checked, {len(errors)} error(s)')
sys.exit(1 if errors else 0)
"
```

Report any files that fail. All files must parse cleanly before presenting changes to the user.
