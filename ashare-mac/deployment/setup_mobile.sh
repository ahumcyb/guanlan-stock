#!/bin/bash
# Run as root after code has been copied to /opt/guanlan-app.
set -euo pipefail
test "$(id -u)" = 0
getent group guanlan-control >/dev/null || groupadd --system guanlan-control
id guanlan-worker >/dev/null 2>&1 || useradd --system --create-home --home-dir /var/lib/guanlan-worker --shell /usr/sbin/nologin --gid guanlan-data guanlan-worker
id guanlan-api >/dev/null 2>&1 || useradd --system --create-home --home-dir /var/lib/guanlan-api --shell /usr/sbin/nologin guanlan-api
usermod -a -G guanlan-control guanlan-worker
usermod -a -G guanlan-control,guanlan-data guanlan-api
install -d -o root -g root -m 755 /opt/guanlan-app
install -d -o root -g guanlan-data -m 750 /etc/guanlan-mobile
install -d -o root -g root -m 700 /etc/guanlan-mobile/tls
install -d -o guanlan-worker -g guanlan-data -m 750 /srv/guanlan-mobile /srv/guanlan-mobile/releases
install -d -o guanlan-worker -g guanlan-control -m 2770 /srv/guanlan-mobile/jobs /srv/guanlan-mobile/incoming
touch /srv/guanlan-mobile/jobs/.queue.lock
chown guanlan-worker:guanlan-control /srv/guanlan-mobile/jobs/.queue.lock
chmod 660 /srv/guanlan-mobile/jobs/.queue.lock
install -d -o guanlan-worker -g guanlan-data -m 700 /srv/guanlan-mobile/work /srv/guanlan-mobile/overlay
chown -R guanlan-worker:guanlan-data /srv/guanlan-data
chmod 750 /srv/guanlan-data /srv/guanlan-data/releases
install -d -o guanlan-worker -g guanlan-data -m 750 /srv/guanlan-data/staging
if [ ! -f /etc/guanlan-mobile/tls/server.key ]; then
  openssl req -x509 -newkey rsa:3072 -sha256 -nodes -days 730 \
    -keyout /etc/guanlan-mobile/tls/server.key -out /etc/guanlan-mobile/tls/server.crt \
    -subj /CN=106.14.125.189 \
    -addext subjectAltName=IP:106.14.125.189 \
    -addext basicConstraints=critical,CA:TRUE \
    -addext keyUsage=critical,digitalSignature,keyEncipherment,keyCertSign \
    -addext extendedKeyUsage=serverAuth >/dev/null 2>&1
fi
chmod 600 /etc/guanlan-mobile/tls/server.key
openssl x509 -in /etc/guanlan-mobile/tls/server.crt -outform der -out /etc/guanlan-mobile/tls/server.der
if [ ! -f /var/lib/guanlan-mobile.swap ]; then
  fallocate -l 4G /var/lib/guanlan-mobile.swap
  chmod 600 /var/lib/guanlan-mobile.swap
  mkswap /var/lib/guanlan-mobile.swap >/dev/null
fi
if ! swapon --show=NAME --noheadings | grep -Fxq /var/lib/guanlan-mobile.swap; then swapon /var/lib/guanlan-mobile.swap; fi
if ! grep -Fq '/var/lib/guanlan-mobile.swap ' /etc/fstab; then
  printf '/var/lib/guanlan-mobile.swap none swap sw 0 0\n' >> /etc/fstab
fi
# Small ECS images may set swappiness=0. That prevents useful anonymous-page
# reclaim inside the worker's memory limit and stalls its heartbeat as well.
printf 'vm.swappiness=60\n' > /etc/sysctl.d/90-guanlan-mobile-swap.conf
sysctl -p /etc/sysctl.d/90-guanlan-mobile-swap.conf >/dev/null
if [ ! -x /opt/guanlan-app/.venv/bin/python ]; then python3 -m venv /opt/guanlan-app/.venv; fi
/opt/guanlan-app/.venv/bin/pip install --disable-pip-version-check --index-url https://pypi.org/simple -r /opt/guanlan-app/requirements.lock
printf 'Mobile runtime and private TLS certificate ready\n'
