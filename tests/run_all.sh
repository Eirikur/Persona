#!/bin/bash

# Runs every fast, service-free test (tests/test_*.py) and reports which
# failed. Safe at any time: none of them start a service, touch the live
# stack, or make a sound. Exit code 0 = everything passed.
#
# Usage: tests/run_all.sh

cd "$(dirname "$0")/.." || exit 1

failed=""

for test in tests/test_*.py; do
    if "$test" > /dev/null 2>&1; then
        echo "PASS  $test"
    else
        echo "FAIL  $test   (run it on its own to see which case)"
        failed="$failed $test"
    fi
done

if [ -n "$failed" ]; then
    exit 1
fi
