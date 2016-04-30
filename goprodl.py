from __future__ import unicode_literals
import requests
import os
import shutil
import sys
import time
import datetime
import uuid
from bs4 import BeautifulSoup


def log(txt, nl=True, ts=True):
    if nl:
        txt = "{} {}\n".format(datetime.datetime.now(), txt)
    sys.stdout.write(txt)


def lookahead(iterable):
    """
    Pass through all values from the given iterable, augmented by the
    information if there are more values to come after the current one
    (True), or if it is the last value (False).
    """
    # Get an iterator and pull the first value.
    it = iter(iterable)
    last = next(it)
    # Run the iterator to exhaustion (starting from the second value).
    for val in it:
        # Report the *previous* value (more to come).
        yield last, True
        last = val
    # Report the last value.
    yield last, False


def find_directory_links(tag):
    return (
        tag.name == 'a' and
        tag.has_attr('class') and
        'GOPRO' in tag.attrs['href']
    )


def find_image_links(tag):
    return (
        tag.name == 'a' and
        tag.has_attr('class') and
        tag.attrs['href'].lower().endswith('.jpg')
    )


def list_images():
    base_url = 'http://10.5.5.9/videos/DCIM/'
    log("--> listing base directories from: {}".format(base_url))
    index = BeautifulSoup(
        requests.get(base_url).content,
        'html.parser',
    )
    directories = index.find_all(find_directory_links)
    for directory in directories:

        directory_url = "".join([base_url, directory.attrs['href']])
        log("--> listing images from: {}".format(directory_url))
        images = BeautifulSoup(
            requests.get(directory_url).content,
            'html.parser',
        ).find_all(find_image_links)
        for image in images:
            image_url = "".join([directory_url, image.attrs['href']])
            yield image_url


def download_all_images(target_dir='', skip_existing=True, delete_after_download=False, check=None, use_subdirs=False, sleep_between_images=3.0):
    log("==> DOWNLOADING images to {}".format(target_dir))
    target_dir = os.path.abspath(target_dir)
    for image_url, has_more in lookahead(list_images()):
        local_filename = image_url.split('/')[-1]
        local_subdir = image_url.split('/')[-2]
        if use_subdirs:
            local_filepath = os.path.abspath(os.path.join(target_dir, local_subdir, local_filename))
        else:
            local_filepath = os.path.abspath(os.path.join(target_dir, local_filename))
        if skip_existing and os.path.exists(local_filepath):
            log('   skipping download of {}'.format(image_url))
            if delete_after_download:
                if has_more:
                    delete_image(image_url)
                else:
                    log('not deleting previously downloaded {} because it is the last one standing'.format(image_url))
            continue
        log('--> downloading {}'.format(image_url))
        log('    to: {}'.format(local_filepath))
        real_delete_after_download = delete_after_download and has_more
        download(image_url, target_path=local_filepath, delete_after_download=real_delete_after_download, check=check)
        if delete_after_download and not real_delete_after_download:
            log('did not delete {} because it is the last one standing'.format(image_url))
        # desparate attempt to not have the gopro crash
        log('    sleeping for {}s, so gopro does not crash'.format(sleep_between_images))
        time.sleep(sleep_between_images)



def download(url, target_path=None, delete_after_download=False, check=None):
    if target_path is None:
        target_path = os.path.abspath(url.split('/')[-1])
    target_path = os.path.abspath(target_path)
    target_dir = os.path.dirname(target_path)
    target_path_tmp = os.path.join(target_dir,
        target_dir,
        '.partial-download.{}.{}'.format(uuid.uuid4(), os.path.basename(target_path)),
    )
    if check:
        if not check():
            raise Exception('[!!!!]-> stick not connected!')
    if not os.path.exists(target_dir):
        os.makedirs(target_dir)
    r = requests.get(url, stream=True)
    try:
        with open(target_path_tmp, 'wb') as f:
            for chunk in r.iter_content(chunk_size=1024):
                if chunk:
                    f.write(chunk)
    except Exception as e:
        log("ERROR DOWNLOADING IMAGE: {}".format(e))
        try:
            os.remove(target_path)
        except:
            pass
    else:
        shutil.move(target_path_tmp, target_path)
        if delete_after_download:
            delete_image(url)
    return target_path


def delete_image(url):
    # TODO: implement
    rel_path = url.split('/DCIM')[-1]
    log('deleting {}'.format(rel_path))
    requests.get(
        "http://10.5.5.9/gp/gpControl/command/storage/delete?p={}".format(rel_path),
        #params={'p': rel_path}
    )


def check_stick_connected(path):
    # checks whether the .itsmounted file exists in the path
    filepath = os.path.join(path, '.itsmounted')
    #log("Checking if stick connected: {}".format(filepath))
    return os.path.exists(filepath)
