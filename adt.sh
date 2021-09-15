#!/bin/bash

# adt - helper frontend for lxd autopkgtest

# autopkgtest-buildvm-ubuntu-cloud -rimpish
# autopkgtest xfig_3.2.8-2.dsc -- qemu /srv/qemu/autopkgtest-impish-amd64.img --ram-size=1592 --cpus=1
# autopkgtest xfig_3.2.8-2.dsc -- qemu /srv/qemu/autopkgtest-impish-amd64.img --ram-size=8192 --cpus=4

if [ -n "$1" ] ; then
    series="$1"
    shift
else
    series="$(distro-info -d)"
fi

if [ -n "$1" ] ; then
    target="$1"
    shift
fi

function getdistro () {
    if distro-info -a | grep -q "$1" ; then
        echo "ubuntu"
        return
    fi

    case "$1" in
        stable|testing|unstable|sid|buster|bullseye|bookworm)
            echo "debian";;
        *)
            echo "unknown";;
    esac
}

dist=$(getdistro "$series")

if [ -z "$target" ] ; then
    if [ "$(ls -l *dsc | wc -l)" -gt "1" ] ; then
        echo "cannot auto find target - too many dsc files"
        exit 1
    fi
    target=$(echo *dsc)
fi

image="autopkgtest/$dist/$series/$(dpkg --print-architecture)"

if ! lxc image list | grep -q $image ; then
    echo "image $image not found - do we need to create it?"
    echo "consider command:"
    echo "autopkgtest-build-lxd images:$dist/$series"
    exit 1
fi

set -x
autopkgtest $@ $target -- lxd $image
