#!/bin/sh
# Start: ./run.sh          (echtes GitLab, braucht config.json und GITLAB_TOKEN)
#        ./run.sh --demo   (erfundene Daten)
cd "$(dirname "$0")" || exit 1
# Mit venv (z. B. wegen keyring) wird automatisch deren Python genommen
PY=python3; [ -x .venv/bin/python ] && PY=.venv/bin/python
exec "$PY" server.py "$@"
