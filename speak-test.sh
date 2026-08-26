#!/bin/bash

set -euo pipefail

URL="http://127.0.0.1:8402/speak"
TEXT="${*:-Hello. This is a direct speech output test.}"

curl -X POST "$URL" \
    -H "Content-Type: application/json" \
    --data-binary @- <<JSON
{"text": "$TEXT"}
JSON
