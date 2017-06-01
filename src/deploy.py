import abc, pycurl, sys, os, tempfile, hashlib, json, time, subprocess, re
import logging, requests, fnmatch, shutil
from util import namedtuple_from_mapping
from zipfile import ZipFile
from collections import OrderedDict
from flask import request
from werkzeug.utils import secure_filename
from tempfile import TemporaryDirectory

vars_regex = re.compile('{(.*?)}')
prefix_regex = re.compile('{base_url}/?')

file_dir = os.path.dirname(os.path.realpath(__file__))
deploy_script = os.path.join(file_dir, 'deploy.sh')

def get_platform(platform):
    if "osx" in platform.lower():
        return "OSX"
    if "windows" in platform.lower():
        return "Windows"
    return "Linux";

def inject_variables(path_format, vars_obj):
    matches = vars_regex.findall(path_format)
    path = path_format
    for match in matches:
        target = '{%s}' % match
        if isinstance(vars_obj, dict) and match in vars_obj:
            path = path.replace(target, str(vars_dict[match]))
        else:
            replacement = getattr(vars_obj, match, None)
            if replacement is not None:
                path = path.replace(target, str(replacement))
    return path


def hashf(file_source, block_size=65536):
    hasher = hashlib.sha256()
    for block in iter(lambda: file_source.read(block_size), b''):
        hasher.update(block)
    return hasher.hexdigest()


def hash_file(filepath, block_size=65536):
    with open(filepath, 'rb') as file_source:
        return hashf(file_source, block_size)


def create_file_summary(filepath):
    return {
        "size": os.path.getsize(filepath),
        "sha256": hash_file(filepath)
    }

def download_file(url, path):
    with open(path, 'wb') as target_file:
        curl = pycurl.Curl()
        curl.setopt(curl.URL, url)
        curl.setopt(curl.WRITEDATA, target_file)
        curl.perform()
        curl.close()


def unzip_to_dir(file_path, dst_dir):
    with ZipFile(file_path) as zip_file:
        zip_file.extractall(path=dst_dir)


def cloudflare_purge(config, url):
    cloudflare_api = 'https://api.cloudflare.com/client/v4/zones/%s/purge_cache'
    cloudflare_api = cloudflare_api % config.CLOUDFLARE_ZONE_ID
    print('Purging cache for %s via %s' % (url, cloudflare_api))
    clear_response = requests.delete(cloudflare_api,
            headers= {
                'Content-Type': 'application/json',
                'X-Auth-Email': config.CLOUDFLARE_EMAIL,
                'X-Auth-Key': config.CLOUDFLARE_API_KEY
            },
            json={
                'files': [url]
            })
    print(clear_response.request)
    print(clear_response.json())
    clear_response.raise_for_status()


def deploy_from_url(event):
    try:
        tempdir = tempfile.TemporaryDirectory()
        temp_dir = tempdir.name

        zip_path = os.path.join(temp_dir, 'build.zip')
        print('Downloading ZIP File to %s' % zip_path)
        download_file(event.download_url, zip_path)

        temp_data_dir = os.path.join(temp_dir, 'data')
        print('Unzipping ZIP file to: %s' % temp_data_dir)
        os.makedirs(temp_data_dir)
        unzip_to_dir(zip_path, temp_data_dir)
        os.remove(zip_path)
        abs_dir_path = os.path.abspath(temp_data_dir)

        if 'PROJECTS' in event.config._asdict() and event.project in event.config.PROJECTS:
            json_index = OrderedDict(event.config.PROJECTS[event.project])
        else:
            json_index = OrderedDict()

        if 'EXCLUDE_FILES' in event.config._asdict():
            exclude_files = list(event.config.EXCLUDE_FILES)
        else:
            exclude_files = list()

        json_index['base_url'] = event.base_url
        json_index['project'] = event.project
        json_index['branch'] = event.branch
        json_index['platform'] = event.platform
        json_index['last_updated'] = int(time.time())
        files = OrderedDict()
        for directory, _, dir_files in os.walk(abs_dir_path):
            for file in dir_files:
                full_path = os.path.join(directory, file)
                relative_path = full_path.replace(abs_dir_path + os.path.sep, '')
                if any(fnmatch.fnmatch(relative_path, pattern) for pattern in exclude_files):
                    print("Excluding %s" % full_path)
                    continue
                summary = create_file_summary(full_path)

                # Append the hash of the file to its filename to cache bust
                os.rename(full_path, full_path + '_' + summary['sha256'])
                files[relative_path] = summary

        json_index["files"] = files
        with open(os.path.join(temp_data_dir, 'index.json'), 'w') as index:
            json.dump(json_index, index)

        dest_dir = prefix_regex.sub(event.base_dir, event.url_format)
        dest_dir = inject_variables(dest_dir, event)
        print('Moving completed files from %s to %s' % (temp_data_dir, dest_dir))
        # Forcibly move and replace files. This should be an atomic change

        if os.path.exists(dest_dir):
            shutil.rmtree(dest_dir)
        os.rename(temp_data_dir, dest_dir)

        for directory, _, dir_files in os.walk(dest_dir):
            if any(fnmatch.fnmatch(directory, pattern) for pattern in exclude_files):
                shutil.rmtree(directory)
            for file in dir_files:
                full_path = os.path.join(directory, file)
                relative_path = full_path.replace(abs_dir_path + os.path.sep, '')
                if os.path.exists(full_path) and any(fnmatch.fnmatch(relative_path, pattern) for pattern in exclude_files):
                    os.remove(full_path)
        # Purge CDN cache for index
        index_url_format = "{base_url}/{project}/{branch}/{platform}/index.json"
        index_url = inject_variables(index_url_format, event)
        cloudflare_purge(event.config, index_url)
    finally:
        tempdir.cleanup()


class DeployEvent(object):

    def __init__(self, project, branch, platform, config):
        self.project = project
        self.branch = branch
        self.platform = platform
        self.config = config


class UnityDeployEvent(DeployEvent):

    def __init__(self, project, branch, config, platform, download_url):
        super().__init__(project, branch, platform, config)
        self.url_format = '{base_url}/{project}/{branch}/{platform}'
        self.base_url = config.BASE_URL
        self.download_url = download_url
        self.base_dir = config.BASE_DIR


class DeployHandler(object):

    def __init__(self, config, notifiers=None):
        self.config = config
        if not notifiers:
            notifiers = []
        self.notifiers = list(notifiers)

    @abc.abstractmethod
    def deploy(self, event):
        raise NotImplementError

    def send_notifications(self, message):
        for notifier in self.notifiers:
            notifier.notify(message)


class GitDeploy(DeployHandler):

    def deploy(self, event):
        git_dir = os.path.join(self.config.GIT_ROOT_PATH, event.project, '.git')
        if not os.path.isdir(git_dir):
            return "{} is not a valid project".format(event.project), 400
        branches = requests.get("https://api.github.com/repos/{0}/{1}/branches".format(
            self.config.GITHUB_ORG, event.project)).json()
        has_branch = any(event.branch == name for name in map(lambda x: x['name'], branches))
        if not has_branch:
            return 'Invalid branch', 400
        subprocess.Popen((deploy_script, event.project, event.branch))


class UploadDeploy(DeployHandler):

    def deploy(self, event):
        git_dir = os.path.join(self.config.GIT_ROOT_PATH, event.project, '.git')
        if not os.path.isdir(git_dir):
            return "{} is not a valid project".format(event.project), 400
        branches = requests.get("https://api.github.com/repos/{0}/{1}/branches".format(
            self.config.GITHUB_ORG, event.project)).json()
        has_branch = any(event.branch == name for name in map(lambda x: x['name'], branches))
        if not has_branch:
            return 'Invalid branch', 400
        project = event.config.PROJECTS.get(event.project)
        if not project:
            raise RuntimeError('No project configuration for %s has been set')
        base_url = inject_variables(project['url'], event)
        base_dir = inject_variables(project['download_location'], event)
        if not os.path.exists(base_dir):
            os.makedirs(base_dir)
        upload = request.files.get('file')
        if not upload:
            return 'No uploaded file.', 400
        filename = secure_filename(upload.filename)
        path = os.path.join(base_dir, filename)
        hash_path = os.path.join(base_dir, filename) + '.hash'
        file_hash = hashf(upload)
        print("Saving %s to %s (hash: %s)..." % (filename, path, file_hash))
        upload.seek(0)
        upload.save(path)
        with open(hash_path, 'w') as hash_file:
            hash_file.write(file_hash)
        cloudflare_purge(event.config, os.path.join(base_url, filename))
        cloudflare_purge(event.config, os.path.join(base_url, filename) + '.hash')


BASE_UNITY_URL="https://build-api.cloud.unity3d.com"

class UnityGameDeploy(DeployHandler):

    def __init__(self, config, notifiers=None):
        super().__init__(config, notifiers)
        self.unity_events = {
            "ProjectBuildQueued": self.Standard("queued"),
            "ProjectBuildStarted": self.Standard("started"),
            "ProjectBuildRestarted": self.Standard("restarted"),
            "ProjectBuildSuccess": self.Success,
            "ProjectBuildFailure": self.Failure,
            "ProjectBuildCanceled": self.Standard("canceled"),
        }

    def create_share_link(self, base_url, headers):
        print ('Creating share link...')
        headers = dict(headers)
        headers['Content-Type'] = 'application/json'
        share_request = requests.post(base_url + "/share", headers=headers)
        print ('Response: ' + str(share_request.json()))
        return "https://developer.cloud.unity3d.com/share/{0}/".format(share_request.json()['shareid'])

    def Standard(self, message):
        def _create_content(json, target):
            self.send_notifications("`{}` build #{} for `{}` {}.".format(
                json["projectName"],
                json["buildNumber"],
                json["buildTargetName"],
                message))
        return _create_content

    def Success(self, json, target):
        content = "`{}` build #{} for `{}` finished.".format(
                json["projectName"],
                json["buildNumber"],
                json["buildTargetName"])
        base_url = BASE_UNITY_URL + json['links']['api_self']['href']
        headers = {'Authorization': 'Basic ' + self.config.UNITY_AUTH_TOKEN}
        share_link = "";
        if 'links' in json and 'share_url' in json['links']:
            share_link = json['links']['share_url']["href"]
        else:
            share_link = self.create_share_link(base_url, headers)
        content = content + "\n" + share_link
        self.send_notifications(content)
        req = requests.get(base_url, headers=headers)
        build_obj = req.json()
        branch = build_obj['scmBranch']
        platform = get_platform(build_obj['platform'])
        download_url = build_obj['links']['download_primary']['href']
        unity_event = UnityDeployEvent(target,
                                      branch,
                                      self.config,
                                      platform,
                                      download_url)
        self.send_notifications("Deploying `{}` for `{}`...".format(target, platform))
        deploy_from_url(unity_event)
        self.send_notifications("Deployed `{}` for `{}`...".format(target, platform))

    def Failure(self, json, target):
        content = "`{}` build #{} for `{}` failed.".format(
                json["projectName"],
                json["buildNumber"],
                json["buildTargetName"])
        base_url = BASE_UNITY_URL + json['links']['api_self']['href'] + '/log'
        headers = {'Authorization': 'Basic ' + self.config.UNITY_AUTH_TOKEN}
        req = requests.get(base_url, headers=headers)
        self.send_notifications({ "content": content, "file": req.text })

    def deploy(self, event):
        unity_event= request.headers.get("X-UnityCloudBuild-Event")
        try:
            if unity_event in self.unity_events:
                self.unity_events[unity_event](request.get_json(), event.project)
            else:
                self.send_notifications(unity_event + "\n```json\n" + str(request.get_json()) + "```")
        except Exception as e:
            logging.exception(e)
            self.send_notifications("An error occured with the unity cloud build webhook")
