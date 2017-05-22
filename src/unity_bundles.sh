#!/bin/bash

announce() {
  curl -i -H "Content-Type: application/json" -X POST -d "{\"content\": \"$1\"}" \
    https://discordapp.com/api/webhooks/268475019854610432/goYlK79gCMVqmvxRUIc4Bx0p9TuRdMxHQnynGWe5LbSwpckS0-6eLbx4qHRWqUkNOjRm \
    > /dev/null
}

start() {
  announce ":clock1: $1"
}

success() {
  announce ":white_check_mark: $1"
}

fail() {
  announce ":x: $1"
}

now=$(date +%Y-%m-%d.%H-%M-%S)
LOG_DIR=/var/www/deploy/logs/$1
mkdir -p $LOG_DIR
LOG_FILE="$LOG_DIR/$now.log"

# $1 - Project
# $2 - Branch
# $3 - Platform
# $4 - Download URL

exec > >(tee -i $LOG_FILE)
exec 2>&1

start "Deploying of \`\`$1\`\` from branch \`\`$2\`\` for \`\`$3\`\`..."
PROJECT=$1
BRANCH=$2
PLATFORM=$3
DOWNLOAD_URL=$4
BASE_DIR="/var/www/htfrontend/game"
DIR="$PROJECT\_$BRANCH\_$PLATFORM\_$now"
ZIP="/tmp/$DIR.zip"
TEMP_DIR="/tmp/$DIR/"

CF_AUTH_EMAIL="teahouse.hourai@gmail.com"
CF_AUTH_KEY="c8cc85aeba1f5d368bd3bc2c8994887cfff0f"
ZONE_ID="5da5310f319e691f26ab006efe413072"

purge() {
  URL="https://houraiteahouse.net/game/$PROJECT/$BRANCH/$1"
  echo "Purging CloudFlare caches for $URL"
  curl -X DELETE "https://api.cloudflare.com/client/v4/zones/$ZONE_ID/purge_cache" \
       -H "X-Auth-Email: $CF_AUTH_EMAIL" \
       -H "X-Auth-Key: $CF_AUTH_KEY" \
       -H "Content-Type: application/json" \
       --data "{\"files\":[\"$URL\"]}"
}


echo "Downloading package..."
curl -o $ZIP $DOWNLOAD_URL

echo "Extracting to $TEMP_DIR..."
unzip $ZIP -d $TEMP_DIR > /dev/null

echo "Cleaning up: Deleting $ZIP..."
rm $ZIP

ALWAYS_COPY_SUBDIRS="lang data"

SRC_DIR=$(find $TEMP_DIR -name "StreamingAssets")
DST_DIR="$BASE_DIR/$PROJECT/$BRANCH"
SRC_BUNDLE_DIR=$(find $SRC_DIR -type d -name "$PLATFORM")
DST_BUNDLE_DIR=$(find $DST_DIR -type d -name "$PLATFORM")

echo "Source Directory: $SRC_DIR"
echo "Source Bundle Directory: $SRC_BUNDLE_DIR"
echo "Destination Directory: $DST_DIR"
echo "Destination Bundle Directory: $DST_BUNDLE_DIR"

echo "Copying bundles..."
cp -TRf $SRC_BUNDLE_DIR $DST_BUNDLE_DIR
for SUBDIR in $ALWAYS_COPY_SUBDIRS
do
  echo "Copying $SUBDIR..."
  cp -Rf $SRC_DIR/$SUBDIR $DST_DIR/$SUB_DIR
done

echo "Cleaning up: Deleting $TEMP_DIR..."
rm -rf $TEMP_DIR

purge bundles/$PLATFORM/$PLATFORM
purge data
