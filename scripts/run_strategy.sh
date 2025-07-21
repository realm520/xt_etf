#!/bin/bash
# Unified strategy runner script for XT ETF Trading System
# Usage: ./run_strategy.sh <strategy> [component]
# Example: ./run_strategy.sh stg3l
#          ./run_strategy.sh stg3l netvalue

set -e

# Get the strategy name from first argument
STRATEGY=$1
COMPONENT=${2:-"trading"}  # Default to trading if not specified

# Validate strategy name
if [[ ! "$STRATEGY" =~ ^(stg3l|stg3s|stg5l|stg5s)$ ]]; then
    echo "Error: Invalid strategy '$STRATEGY'"
    echo "Usage: $0 <strategy> [component]"
    echo "Valid strategies: stg3l, stg3s, stg5l, stg5s"
    echo "Valid components: trading (default), netvalue"
    exit 1
fi

# Get the directory of this script
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$( cd "$SCRIPT_DIR/.." && pwd )"

cd "$PROJECT_ROOT"

# Activate virtual environment if it exists
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
elif [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
fi

# Run the appropriate component
case "$COMPONENT" in
    "trading")
        echo "Starting ETF trading strategy: $STRATEGY"
        python run_etf.py --strategy "$STRATEGY"
        ;;
    "netvalue")
        echo "Starting net value calculation for: $STRATEGY"
        python run_net_value.py --strategy "$STRATEGY"
        ;;
    *)
        echo "Error: Unknown component '$COMPONENT'"
        echo "Valid components: trading, netvalue"
        exit 1
        ;;
esac