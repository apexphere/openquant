#!/bin/bash
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
export RUFF_PATH="${DIR}/bin/ruff"
"${DIR}/node/bin/node" "${DIR}/bundle.js" "$@"
