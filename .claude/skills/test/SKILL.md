---
description: Run the TastyMechanics test suite and verify all 299 tests pass
disable-model-invocation: true
allowed-tools: Bash
---

Run the full test suite:

```bash
python3 test_tastymechanics.py
```

Expected: `299 tests | 299 passed | 0 failed` across 24 sections.

If any tests fail, identify the failing section and the cause. Do not mark the task done until all 299 pass.
