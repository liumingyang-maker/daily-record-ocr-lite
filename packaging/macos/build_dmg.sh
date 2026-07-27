#!/usr/bin/env bash
set -euo pipefail

VERSION="${1:?version required}"
MODE="${2:-unsigned}"
APP_PATH="${APP_PATH:-dist/DailyRecordOCR.app}"
OUTPUT_DIR="${OUTPUT_DIR:-artifacts}"
mkdir -p "$OUTPUT_DIR"

STAGING="$(mktemp -d)"
cleanup() { rm -rf -- "$STAGING"; }
trap cleanup EXIT

ditto "$APP_PATH" "$STAGING/DailyRecordOCR.app"
ln -s /Applications "$STAGING/Applications"

if [[ "$MODE" == "formal" ]]; then
  : "${APPLE_DEVELOPER_ID:?APPLE_DEVELOPER_ID is required}"
  : "${APPLE_NOTARY_APPLE_ID:?APPLE_NOTARY_APPLE_ID is required}"
  : "${APPLE_NOTARY_TEAM_ID:?APPLE_NOTARY_TEAM_ID is required}"
  : "${APPLE_NOTARY_PASSWORD:?APPLE_NOTARY_PASSWORD is required}"
  codesign --force --deep --options runtime --timestamp \
    --sign "$APPLE_DEVELOPER_ID" "$STAGING/DailyRecordOCR.app"
  NAME="daily-record-ocr-lite-v${VERSION#v}-macos-arm64.dmg"
else
  NAME="daily-record-ocr-lite-v${VERSION#v}-macos-arm64-UNSIGNED.dmg"
fi

hdiutil create -volname "Daily Record OCR Lite" -srcfolder "$STAGING" \
  -ov -format UDZO "$OUTPUT_DIR/$NAME"

if [[ "$MODE" == "formal" ]]; then
  xcrun notarytool submit "$OUTPUT_DIR/$NAME" --wait \
    --apple-id "$APPLE_NOTARY_APPLE_ID" \
    --team-id "$APPLE_NOTARY_TEAM_ID" \
    --password "$APPLE_NOTARY_PASSWORD"
  xcrun stapler staple "$OUTPUT_DIR/$NAME"
  xcrun stapler validate "$OUTPUT_DIR/$NAME"
fi
