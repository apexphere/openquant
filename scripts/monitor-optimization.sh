#!/bin/bash
# Monitor optimization every 30 minutes for 8 hours
# Resume if dead, log progress

JESSE="/Users/megan/Workspace/openquant/.venv/bin/jesse"
LOG="/Users/megan/Workspace/openquant/storage/logs/optimization-monitor.log"
STRATEGY="RegimeRouterV4"
CHECKS=16  # 8 hours / 30 min

echo "$(date): Starting optimization monitor ($CHECKS checks, every 30 min)" >> "$LOG"

for i in $(seq 1 $CHECKS); do
    sleep 1800  # 30 minutes

    STATUS=$($JESSE status 2>&1)
    echo "$(date): Check $i/$CHECKS — $STATUS" >> "$LOG"

    if echo "$STATUS" | grep -q "running"; then
        # Running, extract progress
        PROGRESS=$(echo "$STATUS" | grep -oE '[0-9]+/[0-9]+' | head -1)
        BEST=$(echo "$STATUS" | grep -oE '[0-9]+\.[0-9]+' | tail -1)
        echo "$(date): OK — progress $PROGRESS, best $BEST" >> "$LOG"
    elif echo "$STATUS" | grep -q "No running"; then
        # Dead — restart
        echo "$(date): DEAD — restarting optimization" >> "$LOG"

        # Check if server is up
        if ! curl -s http://localhost:9000/system/general-info > /dev/null 2>&1; then
            echo "$(date): Server down — restarting" >> "$LOG"
            lsof -i :9000 -t 2>/dev/null | xargs kill 2>/dev/null
            sleep 2
            cd /Users/megan/Workspace/openquant && $JESSE run &
            sleep 8
        fi

        # Resume optimization
        $JESSE optimize $STRATEGY \
            --training-start 2025-06-01 --training-finish 2025-09-30 \
            --testing-start 2025-10-01 --testing-finish 2025-12-31 \
            --timeframe 4h \
            --trials 1000 2>&1 >> "$LOG"
        echo "$(date): Restarted optimization" >> "$LOG"
    fi
done

echo "$(date): Monitor complete" >> "$LOG"
