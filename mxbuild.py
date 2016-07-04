import os
import subprocess
import sys
import json
import errno
sys.path.insert(0, 'lib')
import requests


def _get_mono_path():
    p = '/usr/local/share/mono-3.10.0'
    if os.path.isdir(p):
        return p
    else:
        return '/tmp/mono'


def _get_java_location():
    for possible_java_location in [
        '/usr/lib/jvm/jdk-%s-oracle-x64' % '8u45',
        '/tmp/javasdk/usr/lib/jvm/jdk-%s-oracle-x64' % '8u45',
    ]:
        if os.path.isdir(possible_java_location):
            return possible_java_location
    raise Exception('Java not found!')


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

    java_location = _get_java_location()
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


def run_mx_build():
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
    java_locations = [
        '/usr/lib/jvm/jdk-%s-oracle-x64' % _get_java_version(),
        '/tmp/javasdk/usr/lib/jvm/jdk-%s-oracle-x64' % _get_java_version(),
    ]
    build_errors_json = '/tmp/builderrors.json'
    try:
        os.remove(build_errors_json)
    except OSError as e:
        if e.errno != errno.ENOENT:
            raise

    java_location = None
    for possible_java_location in java_locations:
        if os.path.isdir(possible_java_location):
            java_location = possible_java_location
    if java_location is None:
        raise Exception('Java not found!')
    args = [
        get_mono_path() + '/bin/mono',
        '--config', get_mono_path() + '/etc/mono/config',
        '/tmp/mxbuild/modeler/mxbuild.exe',
        '--target=deploy',
        '--java-home=%s' % java_location,
        '--java-exe-path=%s/bin/java' % java_location,
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
