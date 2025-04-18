# SBD Analytics

A containerized data pipeline for importing powerlifting training data from Google Sheets into PostgreSQL.

## Project Structure
```
└── sbd-analytics/
    ├── db-init/
    │   └── 01_init_training_db.sql    # Schema initialization script
    ├── etl/
    │   ├── Dockerfile                 # ETL service Dockerfile
    │   └── load_training_data.py      # Python loader script
    ├── secrets/
    │   ├── creds.json                 # Service account key (gitignored)
    │   └── sheet_id                   # Google Sheet ID (gitignored)
    ├── .gitignore                     # Ignored files and folders
    ├── docker-compose.yml             # Docker Compose configuration
    └── README.md                      # Project documentation
```

## Prerequisites
- Docker and Docker Compose
- Google Cloud service account with the Sheets API enabled
- Access to the target Google Sheet

## Configuration
1. Place the service account key in `secrets/creds.json`.
2. Store the Google Sheet ID in `secrets/sheet_id` (only the ID string).
3. Confirm that both files are listed in `.gitignore`.

## Setup and Usage
1. Start the database:
   ```bash
   docker compose up -d db
   docker logs my_postgres --tail 20
   ```
2. Run the ETL process:
   ```bash
   docker compose run --rm etl
   ```
3. Verify the imported data:
   ```bash
   docker exec -it my_postgres psql -U myuser -d mydatabase
   \dt
   SELECT * FROM training_blocks LIMIT 5;
   \q
   ```

## Reset and Re-import
To reset the environment and reload data:
```bash
docker compose down
# Replace <volume_name> with the actual volume listed by `docker volume ls`
docker volume rm <volume_name>
docker compose up -d db
docker compose run --rm etl
```

## Development Notes
- The schema initialization script in `db-init/` runs only on an empty data volume.
- The ETL script detects variable numbers of days, exercises, and sets per block.
- Secrets are mounted into the ETL container at `/run/secrets/`.
