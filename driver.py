#!/usr/bin/env python3

"""A custom GitLab runner executor running inside Proxmox LXC containers."""

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
            container.id = parts[0]
            container.status = parts[1]
            container.name = parts[2]
        elif len(parts) == 4:
            container.id = parts[0]
            container.status = parts[1]
            container.lock = parts[2]
            container.name = parts[3]
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


def create(container_id: int, storage: str, image: str):
    """Creates a new container from an image.

    If the image is not available locally this function tries to
    download the image.

    :param str container_id: Container ID for the new container
    :param str storage: Storage where to find/download the image
    :param str image: Container image to create the container from
    """
    print(f"Creating container {container_id}")
    image_path = f"{storage}:vztmpl/{image}"

    images = list_local_images(storage)
    if image_path not in images:
        download_image(storage, image)

    # TODO: Add links to the pipeline, job
    # TODO: add information to description
    description = f"GitLab LXC Runner {container_id}"
    subprocess.check_call(
        [
            PCT_BIN,
            "create",
            str(container_id),
            image_path,
            "--hostname",
            f"lxc-runner-{container_id}",
            "--description",
            description,
            "--rootfs",
            "volume=local-zfs:10",
            "--memory",
            "4096",
            # "--cores",
            # "2",
            "--net0",
            "name=eth0,bridge=vmbr0,ip=dhcp",
            "--unprivileged",
            "1",
            "--features",
            "nesting=1",
            "--timezone",
            "host",
        ],
        shell=False,
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

    print(f"Running stage {stage}")
    subprocess.run([PCT_BIN, "exec", str(container_id), remote_path])


# TODO: Cleanup all option
def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "command",
        help="Command prepare|cleanup|run",
        choices=["prepare", "cleanup", "run"],
    )
    parser.add_argument("--id", help="Container ID", type=int, required=False)

    parser.add_argument(
        "--storage",
        help="Proxmox Storage Bucket",
        type=str,
        default="local",
        required=False,
    )

    parser.add_argument(
        "--image",
        help="Container image to use",
        type=str,
        required=False,
    )
    parser.add_argument(
        "--no-image-env",
        help="Don't override the image from environment variable ",
        type=str,
        required=False,
    )

    parser.add_argument(
        "--all",
        help="Requires cleanup command. Destroys all lxc runner containers",
        action=argparse.BooleanOptionalAction,
    )

    parser.add_argument(
        "options", help="Script to run inside the container", nargs="*", default=[]
    )

    args = parser.parse_args(argv)

    if args.all is not None and args.command != "cleanup":
        print("The all flag only works with the cleanup command.")
        return 4

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

    # print("args")
    # print(args)
    # print("os.env")
    # for name, value in os.environ.items():
    #     print("{0}: {1}".format(name, value))

    # Container ID
    if args.id:
        container_id = args.id
    elif os.getenv("CUSTOM_ENV_CI_JOB_ID"):
        container_id = os.getenv("CUSTOM_ENV_CI_JOB_ID")
    else:
        print(
            "You must either provide the --id flag or the CUSTOM_ENV_CI_JOB_ID environment variable!"
        )
        return 3

    # Storage
    storage = "local"
    if args.storage:
        storage = args.storage
    elif not args.no_image_env and os.getenv("CUSTOM_ENV_storage"):
        storage = os.getenv("CUSTOM_ENV_storage")

    # Image
    image = "ubuntu-22.04-standard_22.04-1_amd64.tar.zst"
    if args.image:
        image = args.image
    elif not args.no_image_env and os.getenv("CUSTOM_ENV_CI_JOB_IMAGE"):
        image = os.getenv("CUSTOM_ENV_CI_JOB_IMAGE")
    else:
        print(f"WARNING: Using default image {image}")

    # Commands
    if args.command == "cleanup" and args.all:
        destroy_all()

    elif args.command == "cleanup":
        destroy(container_id)

    elif args.command == "prepare":
        destroy(container_id)
        create(container_id, storage, image)
        start(container_id, 60)
        provision(container_id)

    elif args.command == "run":
        script = args.options[0]
        stage = args.options[1]
        run(container_id, script, stage)

    else:
        print(f"Unknown command:  {args.command}")
        return 5

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
