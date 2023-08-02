# proxmox-lxc-executor

Execute [GitLab runner](https://docs.gitlab.com/runner/) jobs inside [Proxmox](https://www.proxmox.com/en/proxmox-ve) LXC containers.

## Installation

* Copy `driver.py` and `provisioning.sh` to the Proxmox host
* Register and configure the GitLab runner on the Proxmox host

Example configuration in `/etc/gitlab-runner/config.toml`

```toml
concurrent = 2
check_interval = 0
shutdown_timeout = 0

[session_server]
  session_timeout = 1800

[[runners]]
  name = "testprodmox-lxc"
  url = "https://gitlab.com/"
  id = 42
  token = "_secret-token"
  token_obtained_at = 2023-07-01T00:00:00Z
  token_expires_at = 0001-01-01T00:00:00Z
  executor = "custom"
  builds_dir = "/home/gitlab-runner/builds"
  cache_dir = "/home/gitlab-runner/cache"
  limit = 2

  [runners.cache]
    MaxUploadedArchiveSize = 0

  [runners.custom]
    prepare_exec =  "/opt/gitlab-runner-lxc-driver/driver.py"
    prepare_args = [ "prepare" ]
    prepare_exec_timeout = 1800

    run_exec =  "/opt/gitlab-runner-lxc-driver/driver.py"
    run_args = [ "run" ]

    cleanup_exec = "/opt/gitlab-runner-lxc-driver/driver.py"
    cleanup_args = [ "cleanup" ]
    cleanup_exec_timeout = 600

    graceful_kill_timeout = 200
    force_kill_timeout = 200
```

## Configuration

## Commands

### prepare

Create and provision a LXC container on the Proxmox host.

### run

Execute scripts inside the LXC container.

### cleanup

Stop and remove the LXC container.
