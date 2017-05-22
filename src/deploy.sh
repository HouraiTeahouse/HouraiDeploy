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

exec > >(tee -i $LOG_FILE)
exec 2>&1

start "Starting deploy of \`\`$1\`\` from branch \`\`$2\`\`..."
cd /var/www/deploy/git/$1
echo "Current directory: $(pwd)"
echo "Fetching branch: $2"
git checkout $2
git fetch --depth 1
git reset --hard origin/$2
git status
/var/www/deploy/git/$1.sh $2

if [ $? -eq 0 ]; then
  success "Deployment of \`\`$1\`\` from branch \`\`$2\`\` was successful!"
else
  fail "Deployment of \`\`$1\`\` from branch \`\`$2\`\` failed!"
fi

