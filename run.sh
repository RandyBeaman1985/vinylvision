#!/bin/zsh
cd "$(dirname "$0")"
# replace any previous instance still holding the port
pkill -f vinylvision.main 2>/dev/null && sleep 1
exec .venv/bin/python -m vinylvision.main "$@"
