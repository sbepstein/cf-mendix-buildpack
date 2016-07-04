import os
import subprocess
import sys
import json
import errno
import shutil
import buildpackutil
sys.path.insert(0, 'lib')
import requests

import logging


def _get_dir_or_raise(directory_list, exception_string):
    for possible_dir in directory_list:
        if os.path.isdir(possible_dir):
            return possible_dir
    raise Exception(exception_string)


def _set_up_mono():
    if os.path.isdir('/usr/local/share/mono-3.10.0'):
        return
    buildpackutil.mkdir_p('/tmp/mono')
    buildpackutil.download_and_unpack(
        buildpackutil.get_blobstore_url('/mx-buildpack/mono-3.10.0.tar.gz'),
        '/tmp/',
        CACHE_DIR,
    )


def _get_mono_dir():
    return _get_dir_or_raise([
        '/usr/local/share/mono-3.10.0',
        '/tmp/mono',
    ], 'Mono not found')


def _get_mono_lib_dir():
    return _get_dir_or_raise([
    ], 'Mono lib dir not found')


def _get_jdk_dir():
    return _get_dir_or_raise([
        '/usr/lib/jvm/jdk-%s-oracle-x64' % '8u45',
        '/tmp/javasdk/usr/lib/jvm/jdk-%s-oracle-x64' % '8u45',
    ], 'JDK not found')


def start_mxbuild_server(runtime_version):
    env = dict(os.environ)
    env['LD_LIBRARY_PATH'] = os.path.join('lib', 'mono-lib')
    subprocess.check_call([
        'sed',
        '-i',
        's|/app/vendor/mono/lib/libgdiplus.so|%s|g' % os.path.join(
            'lib', 'mono-lib', 'libgdiplus.so'
        ),
        os.path.join('mono', 'etc', 'mono', 'config'),
    ])
    subprocess.check_call([
        'sed',
        '-i',
        's|/usr/lib/libMonoPosixHelper.so|%s|g' % os.path.join(
            'lib', 'mono-lib', 'libMonoPosixHelper.so'
        ),
        os.path.join('mono', 'etc', 'mono', 'config'),
    ])

    java_location = _get_jdk_dir()
    subprocess.Popen([
        'mono/bin/mono',
        '--config', 'mono/etc/mono/config',
        'mxbuild/%s/modeler/mxbuild.exe' % runtime_version,
        '--serve',
        '--port=6666',
        '--java-home=%s' % java_location,
        '--java-exe-path=%s/bin/java' % java_location,
    ], env=env)


def run_mxbuild_job_on_server(mpr_abs_path):
    response = requests.post(
        'http://localhost:6666/build',
        data=json.dumps({
            'target': 'Deploy',
            'projectFilePath': mpr_abs_path,
            'forceFullDeployment': False
        }),
        headers={
            'Content-Type': 'application/json',
        },
        timeout=120,
    )
    response.raise_for_status()
    return response.json()


def run_mx_build(buildpack_dir):
    env = dict(os.environ)
    env['LD_LIBRARY_PATH'] = os.path.join(BUILDPACK_DIR, 'lib', 'mono-lib')
    subprocess.check_call([
        'sed',
        '-i',
        's|/app/vendor/mono/lib/libgdiplus.so|%s|g' % os.path.join(
            BUILDPACK_DIR, 'lib', 'mono-lib', 'libgdiplus.so'
        ),
        os.path.join(_get_mono_path(), 'etc/mono/config'),
    ])
    subprocess.check_call([
        'sed',
        '-i',
        's|/usr/lib/libMonoPosixHelper.so|%s|g' % os.path.join(
            BUILDPACK_DIR, 'lib', 'mono-lib', 'libMonoPosixHelper.so'
        ),
        os.path.join(_get_mono_path(), 'etc/mono/config'),
    ])
    build_errors_json = '/tmp/builderrors.json'
    try:
        os.remove(build_errors_json)
    except OSError as e:
        if e.errno != errno.ENOENT:
            raise

    jdk_location = _get_jdk_dir()
    args = [
        _get_mono_dir() + '/bin/mono',
        '--config', _get_mono_dir() + '/etc/mono/config',
        '/tmp/mxbuild/modeler/mxbuild.exe',
        '--target=deploy',
        '--java-home=%s' % jdk_location,
        '--java-exe-path=%s/bin/java' % jdk_location,
    ]
    if get_runtime_version() >= 6.4 or os.environ.get('FORCE_WRITE_BUILD_ERRORS'):
        args.append('--write-errors=%s' % build_errors_json)
        logging.debug('Will write build errors to %s' % build_errors_json)

    if os.environ.get('FORCED_MXBUILD_URL'):
        args.append('--loose-version-check')
        logging.warning(
            'Using forced mxbuild version, the model will be converted'
        )
    args.append(get_mpr_file())
    try:
        subprocess.check_call(args, env=env)
    except subprocess.CalledProcessError as e:
        buildstatus_callback(build_errors_json)
        raise e

    for dir_name in ['web', 'model']:
        path = os.rename(
            os.path.join(BUILD_DIR, 'deployment', dir_name),
            os.path.join(BUILD_DIR, dir_name),
        )
    for file_name in os.listdir(BUILD_DIR):
        path = os.path.join(BUILD_DIR, file_name)
        if file_name not in ['.local', 'web', 'model']:
            if os.path.isdir(path):
                shutil.rmtree(path)
            else:
                os.unlink(path)


def _set_up_mx_build(mendix_version, forced_url=None):
    buildpackutil.mkdir_p('/tmp/mxbuild')

    mendix_runtimes_path = '/usr/local/share/mendix-runtimes.git'
    url = os.environ.get('FORCED_MXBUILD_URL')
    if url is None and os.path.isdir(mendix_runtimes_path):
        env = dict(os.environ)
        env['GIT_WORK_TREE'] = '/tmp/mxbuild'

        # checkout the runtime version
        process = subprocess.Popen(
            ['git', 'checkout', str(mendix_version), '-f'],
            cwd=mendix_runtimes_path, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        process.communicate()
        if process.returncode != 0:
            process = subprocess.Popen(
                ['git', 'fetch', '--tags',
                 '&&', 'git', 'checkout', str(mendix_version), '-f'],
                cwd=mendix_runtimes_path, env=env, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            process.communicate()
            if process.returncode != 0:
                # download the mendix runtime version from our blobstore
                url = buildpackutil.get_blobstore_url(
                    '/runtime/mxbuild-%s.tar.gz' % mendix_version
                )
                buildpackutil.download_and_unpack(url, '/tmp/mxbuild', cache_dir='/tmp/downloads')
    elif url is None:
        url = buildpackutil.get_blobstore_url(
            '/runtime/mxbuild-%s.tar.gz' % mendix_version
        )
        buildpackutil.download_and_unpack(url, '/tmp/mxbuild', cache_dir=CACHE_DIR)
    else:
        buildpackutil.download_and_unpack(url, '/tmp/mxbuild', cache_dir='/tmp/downloads')
