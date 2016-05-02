# -*- coding: utf-8 -*-
import contextlib
import functools
import tempfile

import click
import requests
import os
import shutil
import time
import datetime
import uuid
import exifread
import json
import hashlib
import subprocess
from bs4 import BeautifulSoup


def log(txt):
    # txt = "{} {}".format(datetime.datetime.now(), txt)
    click.echo(txt)


def mkdirs(path):
    try:
        os.makedirs(path)
    except os.error:
        if not os.path.exists(path):
            raise


@contextlib.contextmanager
def temporary_directory():
    d = tempfile.mkdtemp()
    try:
        yield d
    finally:
        shutil.rmtree(d)


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


def resize_image(
        source_file,
        source_filename,
        target_dir,
        resolution,
        shot_at,
        optimise=True,
        check=None,
):
    with temporary_directory() as tmpdir:
        tmpfile = os.path.join(tmpdir, source_filename)
        cmd = 'convert {source_file} -resize {resolution} {output}'.format(
            source_file=source_file,
            resolution=resolution,
            output=tmpfile,
        )
        p = subprocess.Popen(cmd, shell=True)
        p.wait()
        if p.returncode:
            raise Exception('[!!!!!] "{}" failed! '.format(cmd))
        if optimise:
            cmd = 'jpegoptim --strip-all {}'.format(tmpfile)
            p = subprocess.Popen(cmd, shell=True)
            p.wait()
            if p.returncode:
                raise Exception('[!!!!!] "{}" failed! '.format(cmd))
        target_file = os.path.join(
            target_dir,
            resolution,
            generate_relative_image_path(
                source_file=tmpfile,
                source_filename=source_filename,
                shot_at=shot_at,
                resolution=resolution,
            )
        )
        check_and_raise(check)
        mkdirs(os.path.dirname(target_file))
        shutil.move(tmpfile, target_file)


def datetime_to_datetimestr(dt):
    return dt.strftime('%Y-%m-%d'), dt.strftime('%Y-%m-%d_%H-%M-%S')


def generate_relative_image_path(source_file, source_filename, shot_at, resolution):
    source_filename, extension = os.path.splitext(source_filename)
    extension = extension[1:]
    folder_date_str, img_date_str = datetime_to_datetimestr(shot_at)
    md5sum = md5(source_file)
    new_filename = '.'.join([
        img_date_str,
        source_filename,
        resolution,
        md5sum,
        extension,
    ])
    new_path = os.path.join(folder_date_str, new_filename)
    return new_path


def process_image(source_file, target_dir, copy, check, resize, **kwargs):
    click.echo(' ==> handling {}'.format(source_file))
    shot_at = extract_exif_date(image_path=source_file)
    click.echo(' --> shot at {}'.format(shot_at))
    source_filename = os.path.basename(source_file)
    if resize:
        for resolution in ['160x120', '320x240', '640x480']:
            click.echo(' --> resizing {}'.format(resolution))
            resize_image(
                source_file=source_file,
                target_dir=target_dir,
                resolution=resolution,
                shot_at=shot_at,
                source_filename=source_filename,
                check=check,
            )
    new_path = os.path.join(
        target_dir,
        'original',
        generate_relative_image_path(
            source_file=source_file,
            source_filename=source_filename,
            shot_at=shot_at,
            resolution='original',
        )
    )
    check_and_raise(check)
    mkdirs(os.path.dirname(new_path))
    if copy:
        shutil.copy(source_file, new_path)
    else:
        shutil.move(source_file, new_path)


def process_all_images(source_dir, **kwargs):
    for filename in os.listdir(source_dir):
        filepath = os.path.join(source_dir, filename)
        if not os.path.isfile(filepath):
            continue
        if filename.startswith('.'):
            continue
        if not filename.lower().endswith('.jpg'):
            continue
        process_image(source_file=filepath, **kwargs)


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


def process_loop(**kwargs):
    mount_check_fail_sleep_duration = kwargs['mount_check_fail_sleep_duration']
    check = kwargs['check']
    hard_exit = kwargs['hard_exit']
    image_process_sleep_duration = kwargs['image_process_sleep_duration']
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
            process_all_images(**kwargs)
        except Exception as e:
            log(e)
        log("--> sleeping for {}s <--".format(image_process_sleep_duration))
        time.sleep(image_process_sleep_duration)
        if hard_exit:
            exit(1)


def upload(copy, source_dir, destination, **kwargs):
    cmd = ' '.join([
        'aws',
        's3',
        'cp' if copy else 'mv',
        source_dir,
        destination,
        '--include', '"*.JPG"',
        '--exclude', '".*"',
        '--acl', 'public-read',
        '--cache-control', 'max-age=604800',
        '--recursive',
    ])
    p = subprocess.Popen(cmd, shell=True)
    p.wait()
    if p.returncode:
        raise Exception('[!!!!!] "{}" failed! '.format(cmd))


def upload_loop(**kwargs):
    mount_check_fail_sleep_duration = kwargs['mount_check_fail_sleep_duration']
    check = kwargs['check']
    hard_exit = kwargs['hard_exit']
    upload_sleep_duration = kwargs['upload_sleep_duration']
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
            upload(**kwargs)
        except Exception as e:
            log(e)
        log("--> sleeping for {}s <--".format(upload_sleep_duration))
        time.sleep(upload_sleep_duration)
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
@click.option('--image-download-sleep-duration', default=3, help='in seconds')
@click.option('--loop/--no-loop', default=False, help='loop forever')
def cli_download(loop, mount_check_file, **kwargs):
    check = functools.partial(check_stick_connected, mount_check_file)
    kwargs['check'] = check
    if loop:
        click.echo('Starting download in loop mode')
        download_loop(**kwargs)
    else:
        download_all_images(**kwargs)


@cli.command(name='process', help='process downloaded images')
@click.option('--source-dir', default='/data/raw-photos')
@click.option('--source-file', default=None, help='handle just this one file. will ignore source-dir and loop')
@click.option('--target-dir', default='/data/processed-photos')
@click.option('--resize/--no-resize', default=True, help='resize the images')
@click.option('--mount-check-file', default='/data/.itsmounted')
@click.option('--hard-exit/--no-hard-exit', default=False)
@click.option('--mount-check-fail-sleep-duration', default=30, help='in seconds')
@click.option('--image-process-sleep-duration', default=60, help='in seconds')
@click.option('--loop/--no-loop', default=False, help='loop forever')
@click.option('--copy/--move', default=False, help='copy or move the file. default: move')
def cli_process(loop, mount_check_file, **kwargs):
    check = functools.partial(check_stick_connected, mount_check_file)
    kwargs['check'] = check
    if kwargs['source_file']:
        # handle
        kwargs.pop('source_dir')
        process_image(**kwargs)
    else:
        kwargs.pop('source_file')
    if loop:
        click.echo('Starting processing in loop mode')
        process_loop(**kwargs)
    else:
        process_all_images(**kwargs)


@cli.command(name='upload', help='upload images')
@click.option('--source-dir', default='/data/processed-photos')
@click.option('--destination', help='the s3 destination. e.g s3://my-bucket-name/')
@click.option('--mount-check-file', default='/data/.itsmounted')
@click.option('--hard-exit/--no-hard-exit', default=False)
@click.option('--mount-check-fail-sleep-duration', default=30, help='in seconds')
@click.option('--upload-sleep-duration', default=60, help='in seconds')
@click.option('--loop/--no-loop', default=False, help='loop forever')
@click.option('--copy/--move', default=False, help='copy or move the file. default: move')
def cli_upload(loop, mount_check_file, **kwargs):
    check = functools.partial(check_stick_connected, mount_check_file)
    kwargs['check'] = check
    if loop:
        click.echo('Starting upload in loop mode')
        upload_loop(**kwargs)
    else:
        upload(**kwargs)


if __name__ == '__main__':
    cli()