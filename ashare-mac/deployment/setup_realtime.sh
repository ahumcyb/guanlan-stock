#!/bin/bash
set -euo pipefail
test "$(id -u)" = 0
test -f /etc/guanlan-mobile/api.json
test -f /etc/guanlan-mobile/worker.env
install -d -o guanlan-worker -g guanlan-control -m 2770 /srv/guanlan-mobile/jobs/realtime
install -d -o guanlan-worker -g guanlan-data -m 700 /srv/guanlan-mobile/realtime-cache
install -o root -g root -m 644 /opt/guanlan-app/deployment/guanlan-realtime.service /etc/systemd/system/guanlan-realtime.service
systemctl daemon-reload
systemctl restart guanlan-mobile-api.service
systemctl enable --now guanlan-realtime.service
systemctl is-active guanlan-mobile-api.service guanlan-realtime.service
