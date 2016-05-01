# -*- coding: utf-8 -*-
import functools

import click
import requests
import os
import shutil
import sys
import time
import datetime
import uuid
import exifread
import json
import hashlib
import subprocess
from bs4 import BeautifulSoup


def log(txt, nl=True):
    if nl:
        txt = "{} {}\n".format(datetime.datetime.now(), txt)
    # sys.stdout.write(txt)
    click.echo(txt)


def mkdirs(path):
    try:
        os.makedirs(path)
    except os.error:
        if not os.path.exists(path):
            raise


def extract_exif_date(image_path):
    with open(image_path, 'rb') as img_file:
        tags = exifread.process_file(img_file)
    datetime_str = str(tags['EXIF DateTimeOriginal'])
    datetime_native = datetime.datetime.strptime(datetime_str + 'UTC', '%Y:%m:%d %H:%M:%S%Z')
    return datetime_native


def md5(fname):
    hash_md5 = hashlib.md5()
    with open(fname, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()


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


def download_all_images(
        target_dir,
        progress_dir,
        skip_existing=True,
        delete_after_download=False,
        check=None,
        image_download_sleep_duration=3.0,
        **kwargs
):
    log("==> DOWNLOADING images to {}".format(target_dir))
    target_dir = os.path.abspath(target_dir)
    progress_dir = os.path.abspath(progress_dir)
    if check_and_raise(check):
        mkdirs(target_dir)
        mkdirs(progress_dir)
    for image_url, has_more in lookahead(list_images()):
        image_filename = image_url.split('/')[-1]
        progress_filename = '{}.json'.format(image_filename)
        progress_filepath = os.path.join(progress_dir, progress_filename)
        if skip_existing and os.path.exists(progress_filepath):
            log('   skipping download of {}'.format(image_url))
            if delete_after_download:
                if has_more:
                    delete_image(image_url)
                else:
                    log('not deleting previously downloaded {} because it is the last one standing'.format(image_url))
            continue
        log('--> downloading {}'.format(image_url))
        real_delete_after_download = delete_after_download and has_more
        raw_image_path = download(
            image_url,
            target_dir=target_dir,
            delete_after_download=real_delete_after_download,
            check=check,
        )
        if raw_image_path and os.path.exists(raw_image_path):
            with open(progress_filepath, 'wb') as f:
                json.dumps({}, f)
        if delete_after_download and not real_delete_after_download:
            log('did not delete {} because it is the last one standing'.format(image_url))
        # desparate attempt to not have the gopro crash
        log('    sleeping for {}s, so gopro does not crash'.format(image_download_sleep_duration))
        time.sleep(image_download_sleep_duration)


def download(url, target_dir, delete_after_download=False, check=None):
    image_filename = url.split('/')[-1]
    target_path_tmp = os.path.join(
        target_dir,
        '.partial-download.{}.{}'.format(uuid.uuid4(), image_filename),
    )
    target_path_dl = os.path.join(
        target_dir,
        image_filename,
    )
    check_and_raise(check)
    if not os.path.exists(os.path.dirname(target_dir)):
        os.makedirs(os.path.dirname(target_dir))
    r = requests.get(url, stream=True)
    try:
        with open(target_path_tmp, 'wb') as f:
            for chunk in r.iter_content(chunk_size=1024):
                if chunk:
                    f.write(chunk)
    except Exception as e:
        log("ERROR DOWNLOADING IMAGE: {}".format(e))
        try:
            os.remove(target_path_tmp)
        except:
            pass
    else:
        if not os.path.exists(os.path.dirname(target_path_dl)):
            os.makedirs(os.path.dirname(target_path_dl))
        shutil.move(target_path_tmp, target_path_dl)
        if delete_after_download:
            delete_image(url)
    return target_path_dl


# def optimise_image(image_path, destination_path, resolution=None):
#     if resolution:
#
#     command = 'jpegoptim {}'.format(image_path)
#     subprocess.Popen(runString[ext] % {'file': path}, shell=True)
#
#
# def rename_image(target_dir, image_path, optimise=True):
#     shot_at = extract_exif_date(image_path=image_path)
#     folder_date_str = shot_at.strftime('%Y-%m-%d')
#     img_date_str = shot_at.strftime('%Y-%m-%d_%H-%M-%S')
#     new_filename = '{}_{}'.format(img_date_str, filename)
#     md5sum = md5(image_path)
#     return new_path


def delete_image(url):
    # TODO: implement
    rel_path = url.split('/DCIM')[-1]
    log('deleting {}'.format(rel_path))
    requests.get(
        "http://10.5.5.9/gp/gpControl/command/storage/delete?p={}".format(rel_path),
        #params={'p': rel_path}
    )


def check_stick_connected(path, filename=None):
    # checks whether the .itsmounted file exists in the path
    if filename:
        filepath = os.path.join(path, '.itsmounted')
    else:
        filepath = path
    return os.path.exists(filepath)


def check_and_raise(check_func):
    if not check_func:
        return
    if not check_func():
        raise Exception('[!!!!]-> stick not connected!')
    return True


def download_loop(**kwargs):
    mount_check_fail_sleep_duration = kwargs['mount_check_fail_sleep_duration']
    check = kwargs['check']
    hard_exit = kwargs['hard_exit']
    image_download_sleep_duration = kwargs['image_download_sleep_duration']
    while True:
        if not check():
            log(
                '[!]-> stick not connected. sleeping for {}s.'.format(
                    mount_check_fail_sleep_duration)
            )
            time.sleep(mount_check_fail_sleep_duration)
            if hard_exit:
                exit(1)
            continue
        try:
            download_all_images(**kwargs)
        except Exception as e:
            log(e)
        log("--> sleeping for {}s <--".format(image_download_sleep_duration))
        time.sleep(image_download_sleep_duration)
        if hard_exit:
            exit(1)


@click.group()
def cli():
    pass


@cli.command(name='download', help='download images from gopro')
@click.option('--target-dir', default='/data/raw-photos')
@click.option('--progress-dir', default='/data/download-progress')
@click.option('--mount-check-file', default='/data/.itsmounted')
@click.option('--hard-exit/--no-hard-exit', default=False)
@click.option('--mount-check-fail-sleep-duration', default=30, help='in seconds')
@click.option('--delete-after-download/--no-delete-after-download', default=False, help='delete images from camera after successful download')
@click.option('--image-download-sleep-duration', default=1, help='in seconds. to prevent gopro crash')
@click.option('--loop/--no-loop', default=False, help='loop forever')
def cli_download(loop, mount_check_file, **kwargs):
    check = functools.partial(check_stick_connected, mount_check_file)
    kwargs['check'] = check
    if loop:
        click.echo('Starting download process in loop mode')
        download_loop(**kwargs)
    else:
        download_all_images(**kwargs)


if __name__ == '__main__':
    cli()