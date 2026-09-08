# Learning Echo plugin

This package is the reference implementation for the managed plugin runtime.
It declares one Tool and one Capability, requests no permissions, and has no
Python dependencies.

Build a local wheel:

```bash
python -m pip wheel --no-deps -w /tmp/deeptutor-plugins examples/plugins/learning_echo
```

Install, review, approve, and roll back through `deeptutor plugin`. The install
step reads `deeptutor.plugin.json` before importing plugin code and creates a
plugin-private virtual environment.
