---
name: verifiable-goals
description: Write tests before implementing. Plan as step → verify. Use when starting a new task or feature.
---

# Verifiable Goals

Every task → test. Make test pass.
Multi-step → plan as `step → verify`.

```python
# BAD: vague
"Add input validation"

# GOOD: verifiable
# 1. write test: invalid input → raises error
# 2. implement validate()
# 3. test passes
import pytest

def test_validate_invalid():
    with pytest.raises(ValueError):
        validate("")
```
