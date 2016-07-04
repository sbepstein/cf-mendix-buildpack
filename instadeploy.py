from BaseHTTPServer import BaseHTTPRequestHandler, HTTPServer
import cgi
import json
import subprocess
import os
import buildpackutil
import mxbuild
from m2ee import logger
import traceback
import threading
import sys
sys.path.insert(0, 'lib')
import requests

ROOT_DIR = os.getcwd() + '/'
MXBUILD_FOLDER = ROOT_DIR + 'mxbuild/'


PROJECT_DIR = '.local/project'
DEPLOYMENT_DIR = os.path.join(PROJECT_DIR, 'deployment')
TMP_PROJECT_DIR = '.local/tmp_project'
TMP2_PROJECT_DIR = '.local/tmp_project_2'

for directory in (
    MXBUILD_FOLDER,
    PROJECT_DIR,
    TMP_PROJECT_DIR,
    DEPLOYMENT_DIR,
    TMP2_PROJECT_DIR
):
    buildpackutil.mkdir_p(directory)


# TODO HARDCODED CRUFT
MPK_FILE = os.path.join(PROJECT_DIR, 'app.mpk')


class InstaDeployThread(threading.Thread):

    def __init__(self, port, restart_callback, reload_callback):
        super(InstaDeployThread, self).__init__()
        self.daemon = True
        self.port = port
        self.restart_callback = restart_callback
        self.reload_callback = reload_callback

    def run(self):
        do_run(self.port, self.restart_callback, self.reload_callback)


def get_mpr_file(PROJECT_DIR):
    for filename in os.listdir(PROJECT_DIR):
        if filename.endswith('.mpr'):
            return os.path.join(PROJECT_DIR, filename)
    raise Exception('could not get runtime_version')


def detect_runtime_version():
    with open('model/metadata.json') as f:
        metadata = json.load(f)
    return metadata['RuntimeVersion']


class MPKUploadHandler(BaseHTTPRequestHandler):

    def do_POST(self):
        try:
            form = cgi.FieldStorage(
                fp=self.rfile,
                headers=self.headers,
                environ={
                    'REQUEST_METHOD': 'POST',
                    'CONTENT_TYPE': self.headers['Content-Type'],
                })
            if 'file' in form:
                data = form['file'].file.read()
                open(MPK_FILE, 'wb').write(data)
                mxbuild_response = build()
                if 'restartRequired' in str(mxbuild_response):
                    logger.info(str(mxbuild_response))
                    logger.info('Restarting app, reloading for now')
#                    self.server.mxbuild_restart_callback()
                    self.server.mxbuild_reload_callback()
                else:
                    logger.info(str(mxbuild_response))
                    logger.info('Reloading model')
                    self.server.mxbuild_reload_callback()
                return self._terminate(200, {
                    'state': 'STARTED',
                }, mxbuild_response)
            else:
                return self._terminate(401, {
                    'state': 'FAILED',
                    'errordetails': 'No MPK found',
                })
        except Exception as e:
            details = traceback.format_exc()
            return self._terminate(500, {'state': 'FAILED', 'errordetails': details})

    def _terminate(self, status_code, data, mxbuild_response=None):
        if mxbuild_response:
            data['buildstatus'] = json.dumps(mxbuild_json['problems'])
        self.send_response(status_code)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        data['code'] = status_code
        self.wfile.write(json.dumps(data))


def ensure_mxbuild_version(version):
    print 'ensuring mxbuild'
    if os.path.isdir(MXBUILD_FOLDER + version):
        return
    else:
        default_mxbuild_url = 'https://cdn.mendix.com/runtime/mxbuild-%s.tar.gz' % version
        mxbuild_url = os.environ.get('FORCED_MXBUILD_URL', default_mxbuild_url)
        subprocess.check_call((
            'wget',
            '-q',
            mxbuild_url,
            '-O', MXBUILD_FOLDER + version + '.tar.gz',
        ))
        subprocess.check_call(('mkdir', '-p', MXBUILD_FOLDER + version))
        subprocess.check_call((
            'tar',
            'xzf',
            MXBUILD_FOLDER + version + '.tar.gz',
            '-C', MXBUILD_FOLDER + version,
        ))
        subprocess.call(('rm', MXBUILD_FOLDER + version + '.tar.gz'))


def copy_build_output_to_disk():
    for name in ('web', 'model'):
        subprocess.call((
            'rsync', '-a',
            os.path.join(DEPLOYMENT_DIR, name) + '/',
            os.path.join(ROOT_DIR, name) + '/',
        ))


def ensure_mono():
    if os.path.isdir(ROOT_DIR + 'mono'):
        return
    else:
        subprocess.check_call((
            'wget',
            '-q',
            'http://cdn.mendix.com/mx-buildpack/mono-3.10.0.tar.gz',
            '-O', ROOT_DIR + 'mono.tar.gz'
        ))
        subprocess.check_call((
            'tar',
            'xzf',
            ROOT_DIR + 'mono.tar.gz',
            '-C', ROOT_DIR
        ))
        subprocess.call(('rm', ROOT_DIR + 'mono.tar.gz'))


def build():
    logger.debug('unzipping ' + MPK_FILE + ' to ' + TMP_PROJECT_DIR)
    subprocess.check_call(('unzip', '-oqq', MPK_FILE, '-d', TMP_PROJECT_DIR))
    logger.debug('rsync to intermediate')
    subprocess.call((
        'rsync', '--recursive', '--checksum', '-v',
        TMP_PROJECT_DIR + '/',
        TMP2_PROJECT_DIR + '/',
    ))
    subprocess.call((
        'rsync', '--recursive', '--update', '-v',
        TMP2_PROJECT_DIR + '/',
        PROJECT_DIR + '/',
    ))
    runtime_version = detect_runtime_version()
    response = run_mxbuild(runtime_version)
    copy_build_output_to_disk()
    return response


def do_run(port, restart_callback, reload_callback):
    ensure_mono()
    runtime_version = detect_runtime_version()
    ensure_mxbuild_version(runtime_version)
    print('Going to listen on port ', port)
    server = HTTPServer(('', port), MPKUploadHandler)
    server.mxbuild_restart_callback = restart_callback
    server.mxbuild_reload_callback = reload_callback
    mxbuild.start_mxbuild_server()
    server.serve_forever()
