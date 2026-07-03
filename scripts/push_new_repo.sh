#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 1 ]; then
  echo "Usage: ./scripts/push_new_repo.sh git@github.com:OWNER/REPO.git"
  exit 1
fi

REMOTE_URL="$1"

git init
git add -A
git commit -m "Initial weather brain scaffold"
git branch -M main
git remote add origin "$REMOTE_URL"
git push -u origin main
