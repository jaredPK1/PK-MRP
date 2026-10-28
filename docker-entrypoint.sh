#!/bin/sh
# One container: the planner loop (pkmrp loop -> data/latest.json) and the
# web app that serves it. Whichever stops first takes the other with it, and
# Docker restarts the pair.
set -e
pkmrp loop --every "${PLAN_EVERY_MINUTES:-60}" &
PLANNER=$!
gunicorn pkmrp.web.wsgi:app --bind 0.0.0.0:8000 --workers 2 --threads 4 --timeout 60 &
WEB=$!
while kill -0 "$PLANNER" 2>/dev/null && kill -0 "$WEB" 2>/dev/null; do sleep 5; done
kill "$PLANNER" "$WEB" 2>/dev/null || true
exit 1
