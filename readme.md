# bikes

Bike Shop Registry — a workshop tracker for clients, bikes and service work.

`index.html` is the whole app. `server.py` serves it on the local network and
keeps one shared database, so every device sees the same data. Python 3
standard library only; nothing to install.

## Run

```sh
python3 server.py          # http://<this machine>:8080
```

`BIKES_PORT`, `BIKES_HOST` and `BIKES_DATA` override the port (8080), bind
address (all interfaces) and data directory (`./data`).

On the projects VM it runs as a user service:

```sh
systemctl --user status bikes      # restart | stop | start
journalctl --user -u bikes -f      # logs
```

## Data

- `data/db.json` — the live database (not in git).
- `data/backups/db-YYYY-MM-DD.json` — the last state of each day, 60 days kept.
- **Data → Export JSON / Import JSON** in the app downloads a backup or
  replaces everything with one. Import is how data from the old
  browser-only version comes across.

Saves are versioned: if two people save at once, the later one merges the
other's changes in (record by record, matched by id) and saves again, so
both keep their work. Each open page checks for other people's changes
every few seconds.
