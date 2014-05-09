#!/usr/bin/python3
#
# Angstrom's ./oebb.sh rewritten
#

import os
import sys
import argparse
import json
import logging
import subprocess
import re

from collections import OrderedDict

# defaults
base_layers = OrderedDict([
    ('meta-oe',                 'meta-openembedded/meta-oe'),
    ('meta-efl',                'meta-openembedded/meta-efl'),
    ('meta-gpe',                'meta-openembedded/meta-gpe'),
    ('meta-gnome',              'meta-openembedded/meta-gnome'),
    ('meta-xfce',               'meta-openembedded/meta-xfce'),
    ('meta-initramfs',          'meta-openembedded/meta-initramfs'),
    ('toolchain-layer',         'meta-openembedded/toolchain-layer'),
    ('meta-multimedia',         'meta-openembedded/meta-multimedia'),
    ('meta-networking',         'meta-openembedded/meta-networking'),
    ('meta-webserver',          'meta-openembedded/meta-webserver'),
    ('meta-ruby',               'meta-openembedded/meta-ruby'),
    ('meta-filesystems',        'meta-openembedded/meta-filesystems'),
    ('meta-perl',               'meta-openembedded/meta-perl'),
    ('meta-kde',                'meta-kde'),
    ('meta-opie',               'meta-opie'),
    ('meta-java',               'meta-java'),
    ('meta-browser',            'meta-browser'),
    ('meta-mono',               'meta-mono'),
    ('meta-qt5',                'meta-qt5'),
    ('meta-systemd',            'meta-openembedded/meta-systemd'),
    ('meta-ros',                'meta-ros'),
])

bsp_layers = OrderedDict([
    ('common-bsp',              'meta-beagleboard/common-bsp'),
    ('meta-ti',                 'meta-ti'),
    ('meta-fsl-arm',            'meta-fsl-arm'),
    ('meta-fsl-arm-extra',      'meta-fsl-arm-extra'),
    ('meta-nslu2',              'meta-nslu2'),
    ('meta-htc',                'meta-smartphone/meta-htc'),
    ('meta-nokia',              'meta-smartphone/meta-nokia'),
    ('meta-openmoko',           'meta-smartphone/meta-openmoko'),
    ('meta-palm',               'meta-smartphone/meta-palm'),
    ('meta-handheld',           'meta-handheld'),
    ('meta-intel',              'meta-intel'),
    ('meta-sugarbay',           'meta-intel/meta-sugarbay'),
    ('meta-crownbay',           'meta-intel/meta-crownbay'),
    ('meta-emenlow',            'meta-intel/meta-emenlow'),
    ('meta-fri2',               'meta-intel/meta-fri2'),
    ('meta-jasperforest',       'meta-intel/meta-jasperforest'),
    ('meta-n450',               'meta-intel/meta-n450'),
    ('meta-sunxi',              'meta-sunxi'),
    ('meta-raspberrypi',        'meta-raspberrypi'),
    ('meta-minnow',             'meta-minnow'),
    ('meta-dominion',           'meta-dominion'),
    #('meta-atmel',              'meta-atmel'),
    #('meta-exynos',             'meta-exynos'),
    #('meta-gumstix-community',  'meta-gumstix-community'),
])

extra_layers = OrderedDict([
    ('meta-linaro',             'meta-linaro/meta-linaro'),
    ('meta-linaro-toolchain',   'meta-linaro/meta-linaro-toolchain'),
    ('meta-beagleboard-extras', 'meta-beagleboard/meta-beagleboard-extras'),
    #('meta-aarch64',            'meta-linaro/meta-aarch64'),
])

os_layers = OrderedDict([
    ('meta-angstrom',           'meta-angstrom'),
])

oe_core_layers = OrderedDict([
    ('meta',                    'openembedded-core/meta'),
])


template_environment = """\
export SCRIPTS_BASE_VERSION={SCRIPTS_BASE_VERSION}
export BBFETCH2={BBFETCH2}
export DISTRO="{DISTRO}"
export DISTRO_DIRNAME="{DISTRO_DIRNAME}"
export OE_BUILD_DIR="{OE_BUILD_DIR}"
export BUILDDIR="{BUILDDIR}"
export OE_BUILD_TMPDIR="{OE_BUILD_TMPDIR}"
export OE_SOURCE_DIR="{OE_SOURCE_DIR}"
export OE_LAYERS_TXT="{OE_LAYERS_TXT}"
export OE_BASE="{OE_BASE}"
export PATH="{PATH}"
export BB_ENV_EXTRAWHITE="{BB_ENV_EXTRAWHITE}"
export BBPATH="{BBPATH}"
"""

template_auto_conf = """\
MACHINE ?= "{MACHINE}"
"""

template_bblayers_conf = """\
LCONF_VERSION = "5"

BBPATH = "{BBPATH}"

BBFILES = ""

# These layers hold recipe metadata not found in OE-core, but lack any machine or distro content
BASELAYERS ?= " \\
{BASELAYERS}"

# These layers hold machine specific content, aka Board Support Packages
BSPLAYERS ?= " \\
{BSPLAYERS}"

# Add your overlay location to EXTRALAYERS
# Make sure to have a conf/layers.conf in there
EXTRALAYERS ?= " \\
{EXTRALAYERS}"

OS_LAYERS ?= " \\
{OS_LAYERS}"

OE_CORE_LAYERS ?= " \\
{OE_CORE_LAYERS}"

BBLAYERS = " \\
  ${{OS_LAYERS}} \\
  ${{BASELAYERS}} \\
  ${{BSPLAYERS}} \\
  ${{EXTRALAYERS}} \\
  ${{OE_CORE_LAYERS}} \\
"
"""

template_local_conf = """\
CONF_VERSION = "1"

INHERIT += "rm_work"

BBMASK = ""

IMAGE_FSTYPES_append = " tar.xz"
IMAGE_FSTYPES_remove = "tar.gz"

NOISO = "1"

# Avoid dragging in core-image-minimal-initramfs, which drags in grub which in turn fails to build
INITRD_IMAGE = "small-image"

PARALLEL_MAKE     = "-j2"
BB_NUMBER_THREADS = "2"

DISTRO = "{DISTRO}"

MACHINE ??= "{MACHINE}"

DEPLOY_DIR = "{DEPLOY_DIR}/${{TCLIBC}}"
# Don't generate the mirror tarball for SCM repos, the snapshot is enough
BB_GENERATE_MIRROR_TARBALLS = "0"

# Disable build time patch resolution. This would lauch a devshell
# and wait for manual intervention. We disable it.
PATCHRESOLVE = "noop"

# enable PR service on build machine itself
# its good for a case when this is the only builder
# generating the feeds
#
PRSERV_HOST = "localhost:0"
"""

template_site_conf = """\
SCONF_VERSION = "1"

DL_DIR = "{DL_DIR}"

SSTATE_DIR = "{SSTATE_DIR}"

BBFILES ?= "{BBFILES}"

TMPDIR = "{TMPDIR}"
"""


def spawn_process(command_line, out_handler, *args, **kwargs):
    from subprocess import Popen, PIPE, STDOUT

    process = Popen(command_line, *args, stdout=PIPE, stderr=STDOUT, stdin=PIPE, **kwargs)
    encoding = sys.getdefaultencoding()

    output_text = ''
    while not process.poll():
        line = process.stdout.readline()
        if line is None or len(line) == 0:
            break

        line = line.decode(encoding)
        output_text += line

        if out_handler is not None:
            line = line.rstrip()
            if line != '':
                out_handler(line)

    process.wait()
    return process, output_text


def git(*args, cwd=None, silent=False):
    command_line = ['git']
    command_line += args

    process, output = spawn_process(command_line,
                                    lambda msg: logging.info('[git] %s', msg) if not silent else None,
                                    cwd=cwd)


def git_repo_info(path):
    process, output = spawn_process(['git', 'log', '--oneline', '--no-abbrev', '-1'], None, cwd=path)
    revision = output.split(' ')[0]
    process, output = spawn_process(['git', 'branch'], None, cwd=path)
    branch = [line[2:] for line in output.splitlines() if line[0] == '*'][0]
    process, output = spawn_process(['git', 'config', 'remote.origin.url'], None, cwd=path)
    remote_url = output.strip()
    return revision, branch, remote_url


def parse_json(json_str):
    return json.loads(json_str, object_pairs_hook=OrderedDict)


def main():
    """
    Entry point
    """

    configured = True
    arg_parser = argparse.ArgumentParser()
    arg_parser.add_argument('-v', '--verbose', help='increase output verbosity', action='store_true', dest='verbose')
    arg_parser.add_argument('-q', '--quiet', help='do not output status messages', action='store_true', dest='quiet')

    arg_parser.add_argument('-m', '--machine', help='specify target machine', type=str, dest='machine')
    arg_parser.add_argument('-d', '--distro', help='specify target distro', type=str, dest='distro')

    sources_default_path = os.path.join(os.getcwd(), 'sources')
    arg_parser.add_argument('-s', '--sources', help='path to sources directory', type=str, dest='sources',
                            default=sources_default_path)

    build_default_path = os.path.join(os.getcwd(), 'build')
    arg_parser.add_argument('-b', '--build', help='path to build directory', type=str, dest='build',
                            default=build_default_path)

    layers_default_path = os.path.join(sources_default_path, 'layers.txt')
    arg_parser.add_argument('-l', '--layers', help='path to layers.txt', type=str, dest='layers',
                            default=layers_default_path)
    arg_parser.add_argument('-bb', '--bblayers', help='path to json file with entries for bblayers.conf',
                            type=str, dest='bblayers')

    arg_parser.add_argument('-o', '--overwrite', help='overwrite configuration', action='store_true', dest='overwrite')

    args = arg_parser.parse_args()

    # configure logging
    logging_level = logging.CRITICAL if args.quiet else logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(stream=sys.stdout, level=logging_level, format='[%(levelname)-8s]: %(message)s')

    # check some required options
    if not args.machine:
        logging.error('Please specify --machine option')
        configured = False
    if not args.distro:
        logging.error('Please specify --distro option')
        configured = False

    if not args.layers and not args.bblayers:
        logging.error('Please specify --layers and/or --bblayers option')
        configured = False

    if not configured:
        logging.critical('Invalid configuration')
        sys.exit(-1)

    layers_data = OrderedDict()
    if args.layers:
        logging.info('Parsing %s', os.path.basename(args.layers))
        with open(args.layers, 'r') as f:
            for line in f.readlines():
                name, repo, branch, revision = line.strip().split(',')
                layers_data[name] = repo, branch, revision

    bblayers_data = OrderedDict()
    if args.bblayers:
        logging.info('Parsing %s', os.path.basename(args.bblayers))
        with open(args.bblayers, 'r') as f:
            bblayers_data = parse_json(f.read())

            if not args.layers and 'repositories' in bblayers_data:
                layers_data = bblayers_data['repositories']

    for name, repo_data in layers_data.items():
        repo, branch, revision = repo_data
        logging.debug('%s: %s %s %s', name, repo, branch, revision)

    logging.info('Initializing environment')
    distro_folder = re.sub(r'[^A-Za-z0-9]+', '_', args.distro)
    env_file = os.path.join(os.getcwd(), 'env-{0}_{1}'.format(distro_folder, args.machine))
    if args.overwrite and os.path.isfile(env_file):
        os.unlink(env_file)

    build_dir = args.build
    build_tmp_dir = os.path.join(build_dir, 'tmp-{0}'.format(distro_folder))
    path_env = os.pathsep.join([
        os.path.join(args.sources, 'openembedded-core', 'scripts'),
        os.path.join(args.sources, 'bitbake', 'bin')
    ]) + os.pathsep + os.environ['PATH']

    conf_dir = os.path.join(build_dir, 'conf')
    downloads_dir = os.path.join(build_dir, 'downloads')
    deploy_dir = os.path.join(build_dir, 'deploy')
    sstate_cache_dir = os.path.join(build_dir, 'sstate-cache')

    for dir in [conf_dir, downloads_dir, deploy_dir, sstate_cache_dir]:
        if not os.path.isdir(dir):
            os.makedirs(dir)

    extra_white = [
        'MACHINE',
        'DISTRO',
        'TCLIBC',
        'TCMODE',
        'GIT_PROXY_COMMAND',
        'http_proxy',
        'ftp_proxy',
        'https_proxy',
        'all_proxy',
        'ALL_PROXY',
        'no_proxy',
        'SSH_AGENT_PID',
        'SSH_AUTH_SOCK',
        'BB_SRCREV_POLICY',
        'SDKMACHINE BB_NUMBER_THREADS'
    ]

    bb_path_env = build_dir + os.pathsep + os.path.join(args.sources, 'openembedded-core', 'meta')

    if not os.path.isfile(env_file):
        logging.info('Writing environment script')
        with open(env_file, 'w+b') as f:
            f.write(template_environment.format(
                SCRIPTS_BASE_VERSION=0,
                BBFETCH2='True',
                DISTRO=args.distro,
                DISTRO_DIRNAME=distro_folder,
                OE_BUILD_DIR=build_dir,
                BUILDDIR=build_dir,
                OE_BUILD_TMPDIR=build_tmp_dir,
                OE_SOURCE_DIR=args.sources,
                OE_LAYERS_TXT=args.layers,
                OE_BASE=build_dir,
                PATH=path_env,
                BB_ENV_EXTRAWHITE=' '.join(extra_white),
                BBPATH=bb_path_env
            ).encode('utf-8'))

    logging.info('Writing configuration')

    auto_conf_path = os.path.join(conf_dir, 'auto.conf')
    if args.overwrite and os.path.isfile(auto_conf_path):
        os.unlink(auto_conf_path)

    bblayers_conf_path = os.path.join(conf_dir, 'bblayers.conf')
    if args.overwrite and os.path.isfile(bblayers_conf_path):
        os.unlink(bblayers_conf_path)

    local_conf_path = os.path.join(conf_dir, 'local.conf')
    if args.overwrite and os.path.isfile(local_conf_path):
        os.unlink(local_conf_path)

    site_conf_path = os.path.join(conf_dir, 'site.conf')
    if args.overwrite and os.path.isfile(site_conf_path):
        os.unlink(site_conf_path)

    if not os.path.isfile(auto_conf_path):
        logging.info('Writing auto.conf')
        with open(auto_conf_path, 'w+b') as f:
            f.write(template_auto_conf.format(MACHINE=args.machine).encode('utf-8'))

    global base_layers
    global bsp_layers
    global extra_layers
    global os_layers
    global oe_core_layers

    if 'layers' in bblayers_data:
        if 'base' in bblayers_data['layers']:
            base_layers = bblayers_data['layers']['base']

        if 'bsp' in bblayers_data['layers']:
            bsp_layers = bblayers_data['layers']['bsp']

        if 'extra' in bblayers_data['layers']:
            extra_layers = bblayers_data['layers']['extra']

        if 'os' in bblayers_data['layers']:
            os_layers = bblayers_data['layers']['os']

        if 'oe_core' in bblayers_data['layers']:
            oe_core_layers = bblayers_data['layers']['oe_core']

    base_layers_str = ''
    for layer_id, layer in base_layers.items():
        base_layers_str += '  {0} \\\n'.format(os.path.join(args.sources, layer))

    bsp_layers_str = ''
    for layer_id, layer in bsp_layers.items():
        bsp_layers_str += '  {0} \\\n'.format(os.path.join(args.sources, layer))

    extra_layers_str = ''
    for layer_id, layer in extra_layers.items():
        extra_layers_str += '  {0} \\\n'.format(os.path.join(args.sources, layer))

    os_layers_str = ''
    for layer_id, layer in os_layers.items():
        os_layers_str += '  {0} \\\n'.format(os.path.join(args.sources, layer))

    oe_core_layers_str = ''
    for layer_id, layer in oe_core_layers.items():
        oe_core_layers_str += '  {0} \\\n'.format(os.path.join(args.sources, layer))

    if not os.path.isfile(bblayers_conf_path):
        logging.info('Writing bblayers.conf')
        with open(bblayers_conf_path, 'w+b') as f:
            f.write(template_bblayers_conf.format(
                BBPATH=build_dir,
                BASELAYERS=base_layers_str,
                BSPLAYERS=bsp_layers_str,
                EXTRALAYERS=extra_layers_str,
                OS_LAYERS=os_layers_str,
                OE_CORE_LAYERS=oe_core_layers_str,
            ).encode('utf-8'))

    if not os.path.isfile(local_conf_path):
        logging.info('Writing local.conf')
        with open(local_conf_path, 'w+b') as f:
            f.write(template_local_conf.format(
                DISTRO=args.distro,
                MACHINE=args.machine,
                DEPLOY_DIR=deploy_dir
            ).encode('utf-8'))

    if not os.path.isfile(site_conf_path):
        logging.info('Writing site.conf')
        with open(site_conf_path, 'w+b') as f:
            f.write(template_site_conf.format(
                DL_DIR=downloads_dir,
                SSTATE_DIR=sstate_cache_dir,
                BBFILES=os.path.join(args.sources, 'openembedded-core/meta/recipes-*/*/*.bb'),
                TMPDIR=build_tmp_dir
            ).encode('utf-8'))

    # process repositories
    logging.info('Processing sources repositories')
    for name, repo_data in layers_data.items():
        repo, branch, revision = repo_data
        repo_path = os.path.join(args.sources, name)
        if os.path.isdir(repo_path):
            current_revision, current_branch, current_repo = git_repo_info(repo_path)

            logging.info('Checking repository %s', name)
            if current_repo != repo:
                logging.warning('%s is using a different uri "%s" than configured in layers.txt "%s"',
                                name, current_repo, repo)
                logging.warning('Changing uri to "%s"', repo)
                git('remote', 'set-uri', 'origin', repo, cwd=repo_path)
                git('remote', 'update', cwd=repo_path)

            if current_branch != branch:
                logging.warning('%s is using a different branch "%s" than configured in layers.txt "%s"',
                                name, current_branch, branch)
                logging.warning('Changing branch to "%s"', branch)
                git('checkout', '-f', 'origin/{0}'.format(branch), '-b', branch, cwd=repo_path)
                git('checkout', '-f', branch, cwd=repo_path)

            if revision == 'HEAD':
                git('stash', cwd=repo_path, silent=True)
                git('pull', '--rebase', cwd=repo_path)
                git('stash', 'pop', cwd=repo_path, silent=True)
                git('gc', cwd=repo_path, silent=True)
                git('remote', 'prune', 'origin', cwd=repo_path, silent=True)
            elif revision != current_revision:
                git('remote', 'update', cwd=repo_path)
                logging.info('Updating "%s" to %s', name, revision)
                git('stash', cwd=repo_path, silent=True)
                git('reset', '--hard', revision, cwd=repo_path)
                git('stash', 'pop', cwd=repo_path, silent=True)
            else:
                logging.info('Fixed to revision %s, skipping update', revision)
        else:
            logging.info('Cloning repository %s', name)
            git('clone', repo, repo_path)

            if branch != 'master':
                git('checkout', 'origin/{0}'.format(branch), '-b', branch, cwd=repo_path)

            if revision != 'HEAD':
                git('reset', '--hard', revision, cwd=repo_path)

    logging.info('Done')

if __name__ == '__main__':
    main()
