#!/bin/bash
# Manage the Fidelity balance cache service

SERVICE_NAME="com.financial-management.fidelity-cache"
PLIST_SOURCE="/Users/johnalden/Documents/Development/Financial/Financial-Management/config/${SERVICE_NAME}.plist"
PLIST_DEST="$HOME/Library/LaunchAgents/${SERVICE_NAME}.plist"
CACHE_DIR="$HOME/.cache/financial-management"

case "$1" in
    install)
        echo "Installing cache service..."
        mkdir -p "$HOME/Library/LaunchAgents"
        mkdir -p "$CACHE_DIR"
        cp "$PLIST_SOURCE" "$PLIST_DEST"
        launchctl load "$PLIST_DEST"
        echo "Service installed and started."
        echo "Cache will update every 5 minutes."
        echo ""
        echo "View status with: $0 status"
        ;;

    uninstall)
        echo "Uninstalling cache service..."
        launchctl unload "$PLIST_DEST" 2>/dev/null
        rm -f "$PLIST_DEST"
        echo "Service uninstalled."
        ;;

    start)
        echo "Starting cache service..."
        launchctl load "$PLIST_DEST" 2>/dev/null || launchctl start "$SERVICE_NAME"
        echo "Service started."
        ;;

    stop)
        echo "Stopping cache service..."
        launchctl unload "$PLIST_DEST" 2>/dev/null || launchctl stop "$SERVICE_NAME"
        echo "Service stopped."
        ;;

    restart)
        echo "Restarting cache service..."
        launchctl unload "$PLIST_DEST" 2>/dev/null
        sleep 1
        launchctl load "$PLIST_DEST"
        echo "Service restarted."
        ;;

    status)
        echo "=== Service Status ==="
        if launchctl list | grep -q "$SERVICE_NAME"; then
            echo "Service: RUNNING"
            launchctl list "$SERVICE_NAME" 2>/dev/null
        else
            echo "Service: NOT RUNNING"
        fi
        echo ""
        echo "=== Cache Status ==="
        cd /Users/johnalden/Documents/Development/Financial/Financial-Management
        .venv/bin/python -m src.fidelity.cache_service --status
        ;;

    logs)
        echo "=== Recent Logs ==="
        echo "--- fetch.log ---"
        tail -20 "$CACHE_DIR/fetch.log" 2>/dev/null || echo "(no logs)"
        echo ""
        echo "--- launchd stderr ---"
        tail -10 "$CACHE_DIR/launchd-stderr.log" 2>/dev/null || echo "(no errors)"
        ;;

    fetch)
        echo "Running manual fetch (respects market hours)..."
        cd /Users/johnalden/Documents/Development/Financial/Financial-Management
        .venv/bin/python -m src.fidelity.cache_service
        ;;

    fetch-force)
        echo "Running forced fetch (ignores market hours)..."
        cd /Users/johnalden/Documents/Development/Financial/Financial-Management
        .venv/bin/python -m src.fidelity.cache_service --force
        ;;

    *)
        echo "Fidelity Balance Cache Service Manager"
        echo ""
        echo "Usage: $0 {install|uninstall|start|stop|restart|status|logs|fetch|fetch-force}"
        echo ""
        echo "Commands:"
        echo "  install     - Install and start the service (runs every 5 min)"
        echo "  uninstall   - Stop and remove the service"
        echo "  start       - Start the service"
        echo "  stop        - Stop the service"
        echo "  restart     - Restart the service"
        echo "  status      - Show service and cache status"
        echo "  logs        - Show recent log output"
        echo "  fetch       - Run a manual fetch (respects market hours)"
        echo "  fetch-force - Run a manual fetch (ignores market hours)"
        echo ""
        echo "Market hours: Weekdays 9:00 AM - 5:00 PM ET"
        echo "Cache location: $CACHE_DIR/fidelity_balances.json"
        exit 1
        ;;
esac
