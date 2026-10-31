#!/bin/sh
# Inside the container the stand is reached by service name on network qa-shop-net, so the
# SUT_INTERNAL_* addresses from the contract replace the host ones before pytest starts.
set -eu
: "${SUT_ENV_FILE:=/sut/sut.env}"
set -a
# shellcheck disable=SC1090
. "$SUT_ENV_FILE"
set +a
export SUT_BACKEND_URL="$SUT_INTERNAL_BACKEND_URL"
export SUT_DB_READONLY_URL="$SUT_INTERNAL_DB_READONLY_URL"
export SUT_REDIS_URL="$SUT_INTERNAL_REDIS_URL"
exec pytest "$@"
