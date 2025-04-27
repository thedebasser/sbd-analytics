#!/usr/bin/env bash
# Ensure script runs from its directory
cd "$(dirname "$0")"
set -euo pipefail

# Clear previous ETL log so each run starts fresh
LOG_FILE="./logs/etl_debug.log"
echo "🧼 Clearing previous ETL log at $LOG_FILE"
if [ -f "$LOG_FILE" ]; then
  > "$LOG_FILE"
else
  mkdir -p "$(dirname "$LOG_FILE")"
  touch "$LOG_FILE"
fi

echo "⏳ Tearing down existing stack..."
docker compose down --volumes --remove-orphans

echo "🧹 Pruning builder cache..."
docker builder prune --all --force

echo "🏗️  Rebuilding images (no cache..."
docker compose build --no-cache

echo "🗄️  Starting database..."
docker compose up -d db

echo "⌛ Waiting for Postgres to accept connections..."
until docker exec my_postgres pg_isready -U myuser > /dev/null 2>&1; do
  sleep 1
done

echo "🚀 Running ETL job..."
docker compose run --rm etl

echo "🔍 Validating schema..."
if [ -f validate_training_schema.sql ]; then
  echo "ℹ️  Found validate_training_schema.sql, running checks..."
  cat validate_training_schema.sql | docker exec -i my_postgres psql -U myuser -d mydatabase
else
  echo "⚠️  validate_training_schema.sql not found, skipping schema validation."
fi

echo "✅ ETL and validation finished."
