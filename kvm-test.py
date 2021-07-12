#!/usr/bin/env python3

import argparse
import contextlib
import copy
import crypt
import os
import random
import sys
import tempfile
import yaml


cfg = '''
iso:
    basedir: /srv/iso
    release:
        pending: impish/pending/impish-live-server-amd64.iso
        impish: impish/impish-live-server-amd64.iso
        hirsute: hirsute/ubuntu-21.04-live-server-amd64.iso
        groovy: groovy/ubuntu-20.10-live-server-amd64.iso
        focal: focal/ubuntu-20.04.2-live-server-amd64.iso
        bionic: bionic/ubuntu-18.04.5-live-server-amd64.iso
    default: impish
'''

memory = 8 * 1024

def salted_crypt(plaintext_password):
    # match subiquity documentation
    salt = '$6$exDY1mhS4KUYCE/2'
    return crypt.crypt(plaintext_password, salt)


class Context:
    def __init__(self, args):
        self.config = self.load_config()
        self.args = args
        self.release = args.release
        if not self.release:
            self.release = self.config["iso"]["default"]
        self.baseiso = os.path.join(self.config["iso"]["basedir"],
                                    self.config["iso"]["release"][self.release])
        self.curdir = os.getcwd()
        self.iso = f'{self.curdir}/{self.release}-test.iso'
        self.hostname = f'{self.release}-test'
        self.target = f'{self.curdir}/{self.hostname}.img'
        self.password = salted_crypt('ubuntu')
        self.cloudconfig = f'''\
#cloud-config
autoinstall:
    version: 1
    locale:
        en_US.UTF-8
    apt:
        proxy: http://_gateway:1234
    ssh:
        install-server: true
        allow-pw: true
    identity:
        hostname: {self.hostname}
        password: "{self.password}"
        username: ubuntu
'''
    # updates: security
    # ssh:
    #     install-server: true
    #     allow-pw: false
    #     authorized-keys:
    #         - 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIDPkXBpNKXlyND4rHGG1cqoNePnmbQBLaSjbfkYgHswB dbungert@github/49698143 # ssh-import-id gh:dbungert'
    #         - 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIEaPMjkjsCV4B8rmXtZVlmAgKV86zwNG8n9Wq/ro7R6g dbungert@github/53138632 # ssh-import-id gh:dbungert'
    # updates: all
    # interactive-sections:
    #     - network
    # proxy: http://_gateway:3142

    # def update_cc(self, data):
        # cc = yaml.safe_load(ctx.cloudconfig)
        # change to load from a file instead of a string
        # ai = {'autoinstall': yaml.safe_load(ctx.args.autoinstall)}

        # merged = self.merge(cc, ai)
        # ctx.cloudconfig = '#cloud-config\n' + yaml.dump(merged)

    def merge(self, a, b):
        '''Take a pair of dictionaries, and provide the merged result.
           Assumes that any key conflicts have values that are themselves
           dictionaries and raises TypeError if found otherwise.'''
        result = copy.deepcopy(a)

        for key in b:
            if key in result:
                left = result[key]
                right = b[key]
                if type(left) is not dict or type(right) is not dict:
                    result[key] = right
                else:
                    result[key] = self.merge(left, right)
            else:
                result[key] = b[key]

        return result

    def load_config(self):
        result = yaml.safe_load(cfg)
        homecfg = f'{os.environ["HOME"]}/.kvm-test.yaml'
        if os.path.exists(homecfg):
            with open(homecfg, 'r') as f:
                result = self.merge(result, yaml.safe_load(f))

        return result


parser = argparse.ArgumentParser()
parser.add_argument('-r', '--release', action='store', help='target release')
subparsers = parser.add_subparsers(required=True)
scparsers = {}


def subcmd(fn):
    name = fn.__name__
    scparsers[name] = scparser = subparsers.add_parser(name)
    scparser.set_defaults(func=fn)
    return fn


def add_argument(name, *args, **kwargs):
    scparsers[name].add_argument(*args, **kwargs)


def waitstatus_to_exitcode(waitstatus):
    '''If the process exited normally (if WIFEXITED(status) is true), return
    the process exit status (return WEXITSTATUS(status)): result greater
    than or equal to 0.

    If the process was terminated by a signal (if WIFSIGNALED(status) is
    true), return -signum where signum is the number of the signal that
    caused the process to terminate (return -WTERMSIG(status)): result less
    than 0.

    Otherwise, raise a ValueError.'''

    # This function is for python 3.9 compat

    if 'waitstatus_to_exitcode' in dir(os):
        return os.waitstatus_to_exitcode(waitstatus)
    if os.WIFEXITED(waitstatus):
        return os.WEXITSTATUS(waitstatus)
    if os.WIFSIGNALED(waitstatus):
        return -os.WTERMSIG(waitstatus)

    raise ValueError


class SubProcessFailure(Exception):
    pass


def run(cmds):
    for cmd in [line.strip() for line in cmds.splitlines()]:
        if len(cmd) < 1:
            continue
        # semi-simulate "bash -x"
        print(f'+ {cmd}')
        ec = waitstatus_to_exitcode(os.system(cmd))
        if ec != 0:
            raise SubProcessFailure(f'command [{cmd}] returned [{ec}]')


@contextlib.contextmanager
def delete_later(path):
    try:
        yield path
    finally:
        os.remove(path)


@contextlib.contextmanager
def mounter(src, dest):
    run(f'sudo mount -r {src} {dest}')
    try:
        yield
    finally:
        run(f'sudo umount {dest}')


@subcmd
def build(ctx):
    if ctx.args.base:
        ctx.baseiso = ctx.args.base
    run('sudo -v')
    run(f'rm -f {ctx.iso}')
    if ctx.args.quick:
        run(f'sudo ./scripts/quick-test-this-branch.sh {ctx.baseiso} {ctx.iso}')
    else:
        cleanarg = ''
        if not ctx.args.clean:
            cleanarg = 'subiquity'
        with delete_later('subiquity_test.snap') as snap:
            run(f'''
                snapcraft clean --use-lxd {cleanarg}
                snapcraft snap --use-lxd --output {snap}
                test -f {snap}
                sudo ./scripts/inject-subiquity-snap.sh {ctx.baseiso} {snap} \
                    {ctx.iso}
                ''')
    run(f'test -f {ctx.iso}')


add_argument('build', '-q', '--quick', default=False, action='store_true',
             help='build iso with quick-test-this-branch')
add_argument('build', '-c', '--clean', default=False, action='store_true',
             help='agressively clean the snapcraft build env')
add_argument('build', '-b', '--base', action='store', help='specific base iso')


def write(dest, data):
    with open(dest, 'w') as destfile:
        destfile.write(data)


def touch(dest):
    with open(dest, 'w'):
        pass


def create_seed(ctx, tempdir):
    write(f'{tempdir}/user-data', ctx.cloudconfig)
    touch(f'{tempdir}/meta-data')
    seed = f'{tempdir}/seed.iso'
    run(f'cloud-localds {seed} {tempdir}/user-data {tempdir}/meta-data')
    return seed


def drive(path, cache=False):
    kwargs = []
    serial = None
    if cache:
        cparam = 'writethrough'
        format = 'raw'
    else:
        cparam = 'none'
        format = 'qcow2'
        # serial doesn't work..
        # serial = str(int(random.random() * 100000000)).zfill(8)
    kwargs += [f'file={path}']
    kwargs += [f'format={format}']
    kwargs += [f'cache={cparam}']
    kwargs += [ 'if=virtio']
    if serial:
        kwargs += [f'serial={serial}']

    return '-drive ' + ','.join(kwargs)


@subcmd
def install(ctx):
    if os.path.exists(ctx.target):
        if not ctx.args.overwrite:
            print('install refused: will not overwrite existing image')
            sys.exit(1)
        else:
            os.remove(ctx.target)

    run('sudo -v')

    with tempfile.TemporaryDirectory() as tempdir:
        mntdir = f'{tempdir}/mnt'
        os.mkdir(mntdir)
        appends = []

        kvm = ['kvm', '-no-reboot', drive(ctx.target)]

        kvm += ['-m', str(memory)]

        if ctx.args.this:
            iso = ctx.args.this
        elif ctx.args.base:
            iso = ctx.baseiso
        else:
            iso = ctx.iso

        kvm += ['-cdrom', iso]

        if ctx.args.nets > 0:
            for _ in range(ctx.args.nets):
                kvm += ['-nic', 'user,model=virtio-net-pci']
        else:
            kvm += ['-nic', 'none']

        if ctx.args.serial:
            kvm += ['-nographic']
            appends += ['console=ttyS0']

        if ctx.args.autoinstall:
            kvm += [drive(create_seed(ctx, tempdir), True)]
            appends += ['autoinstall']

        if len(appends) > 0:
            kvm += ['-kernel', f'{mntdir}/casper/vmlinuz']
            kvm += ['-initrd', f'{mntdir}/casper/initrd']
            toappend = ' '.join(appends)
            kvm += ['-append', f'"{toappend}"']

        # share = '/home/dbungert/share'
        # tag = 'share'
        # kvm += ['-virtfs']
        # kvm += [f'local,path={share},mount_tag={tag},security_model=none,id={tag}']

        run(f'qemu-img create -f qcow2 {ctx.target} 25G')
        with mounter(iso, mntdir):
            run(' '.join(kvm))


# add_argument('install', '-a', '--autoinstall', default='', action='store',
#              help='merge supplied dict into default autoinstall')
add_argument('install', '-b', '--base', default=False, action='store_true',
             help='use base iso')
add_argument('install', '-a', '--autoinstall', default=False,
             action='store_true', help='use autoinstall')
add_argument('install', '-n', '--nets', action='store', default=1, type=int,
             help='number of network interfaces')
add_argument('install', '-o', '--overwrite', default=False, action='store_true',
             help='allow overwrite of the target image')
add_argument('install', '-s', '--serial', default=False, action='store_true',
             help='attach to serial console')
add_argument('install', '-t', '--this', action='store',
             help='use this iso')

# add_argument('install', '-A', '--arch', default='amd64', action='store',
#              help='Alternate architecture - supported are amd64 (default) ' \
#                   + 'and arm64')


@subcmd
def boot(ctx):
    run(f'kvm -no-reboot -m {memory} {drive(ctx.target)}')


@subcmd
def help(ctx):
    parser.print_usage()
    sys.exit(1)


@subcmd
def cloud(ctx):
    print(ctx.cloudconfig)
    print(ctx.password)


try:
    ctx = Context(parser.parse_args())
except TypeError:
    help()
ctx.args.func(ctx)
