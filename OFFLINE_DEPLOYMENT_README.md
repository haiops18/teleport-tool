# Teleport Cgroup Scanner — Offline Deployment

This bundle is self-contained: all runtime Docker images are under `images/`.
Deployment does not run `docker compose build` and does not pull images from the
internet.

## Requirements

- Linux amd64 host
- Docker Engine, with the current user permitted to run `docker info`
- Docker Compose plugin (`docker compose`) or legacy `docker-compose`
- Port 9999 available on the host

## Install and deploy

```bash
tar -xf teleport-cgroup-scanner-<version>.tar
cd teleport-cgroup-scanner
./deploy.sh
```

On its first run, `deploy.sh` copies `.env.example` to `.env` and securely
generates local MySQL and application secrets. It does not display those
secrets and never overwrites an existing `.env`. Review `.env` before use if
your deployment requires custom settings. Do not commit or distribute `.env`.

Open `http://SERVER_IP:9999` after deployment.

## Operations

```bash
./status.sh
./restart.sh
./stop.sh
./backup.sh
./uninstall.sh           # removes containers/networks only; keeps the DB volume
./uninstall.sh --purge   # asks for confirmation, then also deletes the DB volume
```

`backup.sh` writes a compressed MySQL dump and a protected copy of `.env` to
`backup/`. It deliberately does not back up `data/sessions`, because those
directories can contain Teleport credential material.

## Database migrations

`deploy.sh` starts MySQL first, then runs the bundled idempotent migration
runner before starting the application. `mysql/init.sql` is used only when the
named MySQL volume is first created; it is not re-run for an existing volume.
The migration runner adds the required indexes, service-config tables, and
later columns without resetting existing data.

## Offline verification

Verify the transfer before extracting:

```bash
sha256sum -c teleport-cgroup-scanner-<version>.tar.sha256
```

The bundle includes `tsh` 13.4, 14.4, and 16.4. It contains no live Teleport
sessions, exports, passwords, OTPs, tokens, certificates, private keys, or
production `.env` file.

## Troubleshooting

```bash
./status.sh
docker compose logs -f backend
docker compose logs -f mysql
```

For legacy Compose, replace `docker compose` with `docker-compose`.
