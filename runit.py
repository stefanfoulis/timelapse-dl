import time
import goprodl
import runit_cfg
import functools


if __name__ == "__main__":
    while True:
        if runit_cfg.DEV:
            reload(goprodl)
            reload(runit_cfg)
        check = functools.partial(goprodl.check_stick_connected, runit_cfg.TARGET_DIR)
        if not check():
            goprodl.log('[!]-> stick not connected. sleeping for {}s.'.format(runit_cfg.NO_STICK_SLEEP_DURATION))
            time.sleep(runit_cfg.NO_STICK_SLEEP_DURATION)
            if runit_cfg.HARD_EXIT:
                exit(1)
            continue
        goprodl.log("--> STARTING DOWNLOAD SCRIPT <--")
        try:
            goprodl.download_all_images(
                target_dir=runit_cfg.TARGET_DIR,
                delete_after_download=runit_cfg.DELETE_AFTER_DOWNLOAD,
                sleep_between_images=runit_cfg.SLEEP_BETWEEN_IMAGES,
                check=check,
            )
        except Exception as e:
            goprodl.log(e)
        goprodl.log("--> sleeping for {}s <--".format(runit_cfg.SLEEP_DURATION))
        time.sleep(runit_cfg.SLEEP_DURATION)
        if runit_cfg.HARD_EXIT:
            exit(1)
