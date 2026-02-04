#!/bin/bash
# Setup and deploy to Railway

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

echo "=================================="
echo "Railway Setup Guide"
echo "=================================="
echo ""
echo "1. Create a Railway project at https://railway.app"
echo ""
echo "2. Add PostgreSQL service:"
echo "   - Click 'New' -> 'Database' -> 'PostgreSQL'"
echo ""
echo "3. Get your DATABASE_URL:"
echo "   - Click on PostgreSQL service"
echo "   - Go to 'Variables' tab"
echo "   - Copy the DATABASE_URL value"
echo ""
echo "4. Create .env.railway file:"
echo "   DATABASE_URL=<paste your URL here>"
echo ""
echo "5. Test the sync:"
echo "   ./scripts/sync-to-railway.sh"
echo ""
echo "6. Deploy the web app:"
echo "   - Install Railway CLI: npm install -g @railway/cli"
echo "   - Login: railway login"
echo "   - Link project: railway link"
echo "   - Deploy: railway up"
echo ""
echo "=================================="

# Check if Railway CLI is installed
if command -v railway &> /dev/null; then
    echo "Railway CLI: INSTALLED"
    railway --version
else
    echo "Railway CLI: NOT INSTALLED"
    echo "Install with: npm install -g @railway/cli"
fi

echo ""

# Check for .env.railway
if [ -f ".env.railway" ]; then
    echo ".env.railway: EXISTS"
else
    echo ".env.railway: NOT FOUND"
    echo ""
    echo "Create it with:"
    echo "  cp .env.railway.example .env.railway"
    echo "  # Edit to add your DATABASE_URL"
fi
