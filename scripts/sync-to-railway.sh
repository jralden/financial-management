#!/bin/bash
# Sync local data to Railway PostgreSQL

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

# Check for DATABASE_URL
if [ -z "$DATABASE_URL" ]; then
    # Try to load from .env.railway
    if [ -f ".env.railway" ]; then
        export $(grep -v '^#' .env.railway | xargs)
    else
        echo "ERROR: DATABASE_URL not set"
        echo ""
        echo "Set DATABASE_URL environment variable or create .env.railway file:"
        echo "  DATABASE_URL=postgresql://user:pass@host:port/database"
        echo ""
        echo "Get your DATABASE_URL from Railway dashboard:"
        echo "  1. Go to your project in Railway"
        echo "  2. Click on the PostgreSQL service"
        echo "  3. Go to 'Connect' tab"
        echo "  4. Copy the 'Postgres Connection URL'"
        exit 1
    fi
fi

echo "Syncing to Railway..."
source .venv/bin/activate
python -m src.database.sync

echo ""
echo "Sync complete!"
