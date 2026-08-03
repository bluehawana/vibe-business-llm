#!/usr/bin/env bash
# Regenerate Ichiban.xcodeproj, picking up APPLE_TEAM_ID from ../.env so signing
# is already set on both targets when the project opens.
set -e
cd "$(dirname "$0")"
[ -f ../.env ] && set -a && . ../.env && set +a
export APPLE_TEAM_ID="${APPLE_TEAM_ID:-}"
[ -z "$APPLE_TEAM_ID" ] && echo "  note: APPLE_TEAM_ID not set in ../.env — pick your Team in Xcode by hand"
xcodegen generate
