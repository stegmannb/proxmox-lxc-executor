#!/usr/bin/env bash

set -euo pipefail

# Detect OS and distribution
if [[ -f "/etc/os-release" ]]; then
  . "/etc/os-release"
else
  echo "Provisioning: Could not detect OS"
  exit 1
fi

if [[ "$ID" == "debian" || "${ID_LIKE:-empty}" == "debian" ]]; then
  export DEBIAN_FRONTEND=noninteractive
  arch=$(dpkg --print-architecture)

  apt-get update
  apt-get install --yes git curl

  curl -s "https://packagecloud.io/install/repositories/github/git-lfs/script.deb.sh" | bash
  apt-get install --yes git-lfs

  curl -L --output /usr/local/bin/gitlab-runner "https://gitlab-runner-downloads.s3.amazonaws.com/latest/binaries/gitlab-runner-linux-$arch"
  chmod +x /usr/local/bin/gitlab-runner

elif [[ "$ID" == "arch" || "${ID_LIKE:-empty}" == "arch" ]]; then
  pacman-key --init
  pacman-key --populate archlinux
  pacman -Syuu --noconfirm --needed base-devel curl git git-lfs
#  pacman -Sy --noconfirm --needed

  uname_machine=$(uname --machine)
  if [[ "x86_64" == "$uname_machine" ]]; then
    arch="amd64"
  else
    arch="$uname_machine"
  fi

  curl -L --output /usr/local/bin/gitlab-runner "https://gitlab-runner-downloads.s3.amazonaws.com/latest/binaries/gitlab-runner-linux-$arch"
  chmod +x /usr/local/bin/gitlab-runner

# TODO: provisioning doe snot work on fedora for some reason
#elif [[ "$ID" == "fedora" || "$ID" == "almalinux" || "${ID_LIKE:-empty}" == "fedora" ]]; then
#  yum install -y curl git git-lfs
#
#  uname_machine=$(uname --machine)
#  if [[ "x86_64" == "$uname_machine" ]]; then
#    arch="amd64"
#  else
#    arch="$uname_machine"
#  fi
#
#  curl -L --output /usr/local/bin/gitlab-runner "https://gitlab-runner-downloads.s3.amazonaws.com/latest/binaries/gitlab-runner-linux-$arch"
#  chmod +x /usr/local/bin/gitlab-runner
else
  echo "This distribution is not supported!"
  cat "/etc/os-release"
fi
