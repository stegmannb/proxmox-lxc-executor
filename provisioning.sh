#/usr/bin/env bash

export DEBIAN_FRONTEND=noninteractive

apt-get update
apt-get install --yes git curl

curl -s "https://packagecloud.io/install/repositories/github/git-lfs/script.deb.sh" | bash
apt-get install --yes git-lfs

curl -L --output /usr/local/bin/gitlab-runner "https://gitlab-runner-downloads.s3.amazonaws.com/latest/binaries/gitlab-runner-linux-amd64"
chmod +x /usr/local/bin/gitlab-runner
