#!/usr/bin/env python3

"""Execute GitLab runner jobs inside Proxmox LXC containers."""

from __future__ import annotations

import argparse
import inspect
import os
import shutil
import subprocess
import time
from collections.abc import Sequence
from os import path

global PCT_BIN
global PVEAM_BIN
CI_ENV_PREFIX = "CUSTOM_ENV_"


def list_local_images(storage: str) -> list[str]:
    storage_list: str = subprocess.check_output(
        [PVEAM_BIN, "list", storage], encoding="utf8", text=True
    )
    images: list[str] = storage_list.splitlines()[1:]
    images = [line.split()[0] for line in images]
    return images


def list_online_images(section="system") -> list[str]:
    storage_list: str = subprocess.check_output(
        [PVEAM_BIN, "available", "--section", section], encoding="utf8", text=True
    )
    images: list[str] = storage_list.splitlines()[1:]
    images = [line.split()[1] for line in images]
    return images


def download_image(storage: str, template: str) -> str:
    subprocess.check_call(
        [PVEAM_BIN, "download", storage, template],
        shell=False,
    )
    return f"{storage}:vztmpl/{template}"


def lxc_exists(container_id: int) -> bool:
    try:
        subprocess.check_call(
            [PCT_BIN, "status", str(container_id)],
            shell=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except subprocess.CalledProcessError:
        return False


def lxc_running(container_id: int) -> bool:
    out: str = subprocess.check_output(
        [PCT_BIN, "status", str(container_id)], shell=False, encoding="utf8"
    )
    status = out.strip().split()[-1]
    return status == "running"


def lxc_exists_and_running(container_id: int) -> bool:
    try:
        out: str = subprocess.check_output(
            [PCT_BIN, "status", str(container_id)], shell=False, encoding="utf8"
        )
        status = out.split(" ")[1]
        return status == "running"
    except subprocess.CalledProcessError:
        return False


def list_lxc() -> list[dict[str, str]]:
    output = subprocess.check_output(
        [PCT_BIN, "list"], shell=False, encoding="utf8", text=True
    )
    lines = output.splitlines()[1:]

    containers = []
    for line in lines:
        parts = line.split()
        container = {}
        if len(parts) == 3:
            container["id"] = parts[0]
            container["status"] = parts[1]
            container["name"] = parts[2]
        elif len(parts) == 4:
            container["id"] = parts[0]
            container["status"] = parts[1]
            container["lock"] = parts[2]
            container["name"] = parts[3]
        else:
            raise Exception(f"Cannot read container information from line: {line}")
        containers.append(container)
    return containers


def isolate_service(container_id: int, service: str) -> bool:
    try:
        subprocess.check_call(
            [
                PCT_BIN,
                "exec",
                str(container_id),
                "--",
                "sh",
                "-c",
                "systemctl",
                "isolate",
                service,
            ],
            shell=False,
        )
        return True
    except subprocess.CalledProcessError:
        return False


def is_active_service(container_id: int, service: str) -> bool:
    try:
        subprocess.check_call(
            [
                PCT_BIN,
                "exec",
                str(container_id),
                "--",
                "systemctl",
                "is-active",
                "--quiet",
                service,
            ],
            shell=False,
        )
        return True
    except subprocess.CalledProcessError:
        return False


def destroy_all():
    containers = list_lxc()
    for container in containers:
        if "lxc-runner" in container["name"]:
            container_id = int(container["id"])
            if lxc_running(container_id):
                print(f"Stopping container {container_id}")
                subprocess.check_call([PCT_BIN, "stop", str(container_id)], shell=False)
            subprocess.check_call([PCT_BIN, "destroy", str(container_id)], shell=False)


def destroy(container_id: int) -> bool:
    if not lxc_exists(container_id):
        return False

    if lxc_running(container_id):
        print(f"Stopping container {container_id}")
        subprocess.check_call([PCT_BIN, "stop", str(container_id)], shell=False)

    print(f"Destroying container {container_id}")
    subprocess.check_call([PCT_BIN, "destroy", str(container_id)], shell=False)

    return True


def create(
    container_id: int,
    image: str,
    storage: str = "local",
    image_path: str = "vztmpl",
    hostname: str | None = None,
    cores: int | None = None,
    memory: int | None = None,
    disk_size: int = 10,
    password: str | None = None,
    timezone: str = "host",
    nesting: bool = True,
    unprivileged: bool = True,
):
    """Creates a new container from an image.

    If the image is not available locally this function tries to
    download the image.

    :param bool unprivileged: Makes the container run as unprivileged
        user.
    :param bool nesting: Allow containers access to advanced features.
    :param str timezone: Time zone to use in the container. Can be set
        to "host" to match the host time zone.
    :param str password: Sets root password inside container.
    :param str image_path: Path to the image
    :param str hostname: Set a host name for the container.
    :param int disk_size: Size of the root volume in GB
    :param int memory: Amount of RAM for the container in MB.
    :param int cores: The number of cores assigned to the container. A
        container can use all available cores by default.
    :param str container_id: Container ID for the new container
    :param str storage: Storage where to find/download the image
    :param str image: Container image to create the container from
    """

    image_path = f"{storage}:{image_path}/{image}"
    images = list_local_images(storage)
    if image_path not in images:
        download_image(storage, image)

    print(f"Creating container {container_id}:")

    print(f"       Image:       {image}")

    cmd = [
        PCT_BIN,
        "create",
        str(container_id),
        image_path,
        "--net0",
        "name=eth0,bridge=vmbr0,ip=dhcp",
    ]

    description = f"GitLab LXC Runner {container_id}\n"
    if os.getenv(CI_ENV_PREFIX + "CI_PIPELINE_URL"):
        description = (
            description
            + "[Project]("
            + os.getenv(CI_ENV_PREFIX + "CI_PROJECT_URL")
            + ")\n"
        )
    if os.getenv(CI_ENV_PREFIX + "CI_PIPELINE_URL"):
        description = (
            description
            + "[Pipeline]("
            + os.getenv(CI_ENV_PREFIX + "CI_PIPELINE_URL")
            + ")\n"
        )
    if os.getenv("CI_MERGE_REQUEST_PROJECT_URL"):
        description = (
            description
            + "[Merge request]("
            + os.getenv("CI_MERGE_REQUEST_PROJECT_URL")
            + ")\n"
        )
    cmd.append("--description")
    cmd.append(description)

    cmd.append("--hostname")
    cmd.append(hostname)
    print(f"       Hostname:    {hostname}")

    if cores is not None:
        cmd.append("--cores")
        cmd.append(str(cores))
        print(f"       Cores:       {cores}")

    if memory is not None:
        cmd.append("--memory")
        cmd.append(str(memory))
        print(f"       Memory:      {memory} MB")

    if disk_size is not None:
        cmd.append("--rootfs")
        cmd.append(f"volume=local-zfs:{disk_size}")
        print(f"       Disk size:   {disk_size} GB")

    if password is not None:
        cmd.append("--password")
        cmd.append(password)
        print(f"       Password:    {password}")

    if timezone is not None:
        cmd.append("--timezone")
        cmd.append(timezone)
        print(f"       Timezone:    {timezone}")

    cmd.append("--features")
    features = f"nesting={1 if nesting else 0}"
    cmd.append(features)

    cmd.append("--unprivileged")
    unprivileged = "1" if unprivileged else "0"
    cmd.append(unprivileged)

    subprocess.run(
        cmd,
        shell=False,
        capture_output=True,
        text=True,
    )


def start(container_id: int, timeout: int) -> bool:
    print(f"Starting container {container_id}")

    subprocess.check_call(
        [
            PCT_BIN,
            "start",
            str(container_id),
        ],
        shell=False,
    )

    for i in range(timeout):
        if is_active_service(container_id, "multi-user.target"):
            print(f"Container {container_id} started after {i} seconds")
            return False
        time.sleep(1)

    return False


def provision(container_id: int):
    print(f"Provisioning container {container_id}")

    local_directory = os.path.dirname(
        os.path.abspath(inspect.getfile(inspect.currentframe()))
    )
    local_script = path.join(local_directory, "provisioning.sh")

    remote_script = "/usr/local/bin/provisioning"
    subprocess.check_call(
        [
            PCT_BIN,
            "push",
            str(container_id),
            local_script,
            remote_script,
            "--perms",
            "0755",
            "--user",
            "root",
            "--group",
            "root",
        ],
        shell=False,
        text=True,
    )
    subprocess.check_call(
        [PCT_BIN, "exec", str(container_id), remote_script],
        shell=False,
    )


def run(container_id: int, script: str, stage: str):
    print(f"run: {stage} {script}")

    remote_path = path.join("/usr/local/bin", stage)
    subprocess.run(
        [
            PCT_BIN,
            "push",
            str(container_id),
            script,
            remote_path,
            "--perms",
            "0755",
            "--user",
            "root",
            "--group",
            "root",
        ],
        shell=False,
        capture_output=True,
    )

    print(f"Running {stage} stage")
    subprocess.check_call([PCT_BIN, "exec", str(container_id), remote_path])


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    # general options
    parser.add_argument(
        "--id",
        help="Container ID (default is $CUSTOM_ENV_CI_JOB_ID)",
        type=int,
        required=False,
    )

    subparsers = parser.add_subparsers(title="command", required=True, dest="command")

    # prepare options
    prepare_parser = subparsers.add_parser(
        "prepare", help="Create and provision a new container to run a job"
    )
    prepare_parser.add_argument(
        "--storage",
        help="Proxmox Storage Bucket",
        type=str,
        default="local",
        required=False,
    )
    prepare_parser.add_argument(
        "--image",
        help="Container image to use",
        type=str,
        required=False,
    )
    prepare_parser.add_argument(
        "--no-image-env",
        help="Don't override the image from environment variable",
        type=str,
        required=False,
    )
    prepare_parser.add_argument(
        "--cores",
        help="The number of cores assigned to the container",
        type=int,
        required=False,
    )
    prepare_parser.add_argument(
        "--memory",
        help="Amount of RAM for the container in MB",
        type=int,
        required=False,
    )
    prepare_parser.add_argument(
        "--hostname-prefix",
        help="Use this prefix for the container",
        default="lxc-runner-",
        type=str,
        required=False,
    )
    prepare_parser.add_argument(
        "--password",
        help="Sets root password inside container",
        type=str,
        required=False,
    )

    # run options
    run_parser = subparsers.add_parser("run", help="Run a script inside the container")
    run_parser.add_argument(
        "script", help="Path to the script to run inside the container"
    )
    run_parser.add_argument("stage", help="Name of the stage")

    # cleanup options
    cleanup_parser = subparsers.add_parser(
        "cleanup", help="Stop and destroy the container"
    )
    cleanup_parser.add_argument(
        "--all",
        help="Destroys all lxc runner containers",
        action=argparse.BooleanOptionalAction,
    )

    args: argparse.Namespace = parser.parse_args(argv)

    global PCT_BIN
    PCT_BIN = shutil.which("pct")
    if not PCT_BIN:
        print("Cannot find the pct tool!")
        return 3

    global PVEAM_BIN
    PVEAM_BIN = shutil.which("pveam")
    if not PVEAM_BIN:
        print("Cannot find the pveam tool!")
        return 3

    # config container ID
    if args.id:
        container_id = args.id
    elif os.getenv(CI_ENV_PREFIX + "CI_JOB_ID"):
        container_id = os.getenv(CI_ENV_PREFIX + "CI_JOB_ID")
    else:
        print(
            "You must either provide the --id flag or the CUSTOM_ENV_CI_JOB_ID environment variable!"
        )
        return 3

    # command cleanup --all
    if args.command == "cleanup" and args.all:
        destroy_all()

    # command cleanup
    elif args.command == "cleanup":
        destroy(container_id)

    # command prepare
    elif args.command == "prepare":
        # config storage
        storage = "local"
        if args.storage:
            storage = args.storage
        elif not args.no_image_env and os.getenv(CI_ENV_PREFIX + "runner_storage"):
            storage = os.getenv(CI_ENV_PREFIX + "runner_storage")

        # config image
        if args.image:
            image = args.image
        elif not args.no_image_env and os.getenv(CI_ENV_PREFIX + "CI_JOB_IMAGE"):
            image = os.getenv(CI_ENV_PREFIX + "CI_JOB_IMAGE")
        else:
            image = "ubuntu-22.04-standard_22.04-1_amd64.tar.zst"

        # config cores
        if args.cores:
            cores = args.cores
        elif os.getenv(CI_ENV_PREFIX + "runner_cores"):
            cores = os.getenv(CI_ENV_PREFIX + "runner_cores")
        else:
            cores = None

        # config memory
        if args.memory:
            memory = args.memory
        elif os.getenv(CI_ENV_PREFIX + "runner_memory"):
            memory = os.getenv(CI_ENV_PREFIX + "runner_memory")
        else:
            memory = None

        # config password
        if args.password:
            password = args.memory
        elif os.getenv(CI_ENV_PREFIX + "runner_password"):
            password = os.getenv(CI_ENV_PREFIX + "runner_password")
        else:
            password = None

        destroy(container_id)
        create(
            container_id,
            image,
            storage=storage,
            hostname=args.hostname_prefix + container_id,
            cores=cores,
            memory=memory,
            password=password,
        )
        start(container_id, 60)
        provision(container_id)

    # command run
    elif args.command == "run":
        script = args.script
        stage = args.stage
        run(container_id, script, stage)

    else:
        print(f"Unknown command:  {args.command}")
        return 5

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
