import abc, pycurl, sys, os, tempfile, hashlib, json, time, subprocess, re
import logging, requests, fnmatch, shutil
from util import namedtuple_from_mapping
from zipfile import ZipFile
from collections import OrderedDict
from flask import request

vars_regex = re.compile('{(.*?)}')
prefix_regex = re.compile('{base_url}/?')

file_dir = os.path.dirname(os.path.realpath(__file__))
deploy_script = os.path.join(file_dir, 'deploy.sh')

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


def hash_file(filepath, block_size=65536):
    hasher = hashlib.sha256()
    with open(filepath, 'rb') as file_source:
        for block in iter(lambda: file_source.read(block_size), b''):
            hasher.update(block)
    return hasher.hexdigest()


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
        if not os.path.exists(dest_dir):
            os.makedirs(dest_dir)
        print('Moving completed files from %s to %s' % (temp_data_dir, dest_dir))
        # Forcibly move and replace files. This should be an atomic change
        subprocess.call('cp -Trf %s/ %s/' % (temp_data_dir, dest_dir), shell=True)
        for directory, _, dir_files in os.walk(dest_dir):
            if any(fnmatch.fnmatch(directory, pattern) for pattern in exclude_files):
                shutil.rmtree(directory)
            for file in dir_files:
                full_path = os.path.join(directory, file)
                relative_path = full_path.replace(abs_dir_path + os.path.sep, '')
                if os.path.exists(full_path) and any(fnmatch.fnmatch(relative_path, pattern) for pattern in exclude_files):
                    os.remove(full_path)
    finally:
        tempdir.cleanup()

class DeployEvent(object):

    def __init__(self, project, branch):
        self.project = project
        self.branch = branch

class UnityDeployEvent(DeployEvent):

    def __init__(self, project, branch, config, platform, download_url):
        super().__init__(project, branch)
        self.config = config
        self.url_format = '{base_url}/{project}/{branch}/{platform}'
        self.base_url = config.BASE_URL
        self.download_url = download_url
        self.platform = platform
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
        subprocess.Popen((deploy_script, event.project, branch))

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

    def get_platform(self, platform):
        if "osx" in platform.lower():
            return "OSX"
        if "windows" in platform.lower():
            return "Windows"
        return "Linux";

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
        platform = self.get_platform(build_obj['platform'])
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
