#!/usr/bin/env bash

set -euo pipefail

# Detect OS and distribution
if [ -f /etc/os-release ]; then
    . /etc/os-release
else
  echo "Provisioning: Could not detect OS"
  exit 1
fi

if [[ "$ID_LIKE" == "debian" ]]; then
  export DEBIAN_FRONTEND=noninteractive
  arch=$(dpkg --print-architecture)

  apt-get update
  apt-get install --yes git curl

  curl -s "https://packagecloud.io/install/repositories/github/git-lfs/script.deb.sh" | bash
  apt-get install --yes git-lfs

  curl -L --output /usr/local/bin/gitlab-runner "https://gitlab-runner-downloads.s3.amazonaws.com/latest/binaries/gitlab-runner-linux-$arch"
  chmod +x /usr/local/bin/gitlab-runner
else
  echo "This distribution is not supported!"
  echo "ID: ${ID}"
  echo "ID_LIKE: ${ID_LIKE}"
fi
