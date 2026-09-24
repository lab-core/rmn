"""Writing debug images, cutting a box out of a page, and what memory is left."""

import os
import sys
from datetime import datetime
import cv2
import numpy as np
import psutil
from utils.storage import Storage







ignoreWrite = sys.gettrace() is None and "Debug" not in str(sys.stdin)



storage = Storage()



RED = (225, 6, 0)


GREEN = (0, 154, 23)


ORANGE = (255, 127, 0)


BLACK = (0, 0, 0)




def imwrite_png(name, img, ignore=ignoreWrite):
    if ignore:
        return
    if img.shape[0] == 0 or img.shape[1] == 0:
        return
    if not os.path.exists("images"):
        os.mkdir("images")
    cv2.imwrite("images/%s.png" % name, img)




def imwrite_contours(name, gray, cnts, thick=2, padding=0, ignore=ignoreWrite):
    if ignore:
        return
    gray = gray.copy()
    for c in cnts:
        (x, y, w, h) = cv2.boundingRect(c)
        cv2.rectangle(
            gray,
            (x + padding, y + padding),
            (x + w - padding, y + h - padding),
            (0, 0, 0),
            thick,
        )
    imwrite_png(name, gray)




def fetch_box(img, box):
    # box = (x1, x2, y1, y2) in %
    x = [
        int(box[0] * img.shape[1]),
        int(box[1] * img.shape[1]),
        int(box[2] * img.shape[0]),
        int(box[3] * img.shape[0]),
    ]
    cropped = img[x[2]:x[3], x[0]:x[1]]  # ys and then xs
    imwrite_png("cropped", cropped)
    return cropped




def get_image_from_contour(img, cnt, border=0):
    (x, y, w, h) = cv2.boundingRect(cnt)
    img = img[y + border : y + h - border, x + border : x + w - border]
    imwrite_png("cropped_cnt", img)
    return img




def make_square(img, size=28, margin=0.1):
    # size: size of the square
    # margin: margin in % of the square
    # get size
    h, w = img.shape
    # Create a black image
    s = int((1 + margin) * max(w, h))
    square = np.zeros((s, s), np.uint8)
    y = int((s - h) / 2)
    x = int((s - w) / 2)
    square[y : y + h, x : x + w] = img
    return cv2.resize(square, (size, size))




def get_date():
    # datetime object containing current date and time
    now = datetime.now()

    # dimanche 23 janvier 2022, 23:42
    return now.strftime("%A %d %B %Y, %H:%M")




# files read for the container's memory usage (cgroup v2, then v1); when the
# process is not in a cgroup the resident size of this process is used
CGROUP_MEMORY_FILES = ("/sys/fs/cgroup/memory.current", "/sys/fs/cgroup/memory/memory.usage_in_bytes")




def memory_used_gb(cgroup_files=CGROUP_MEMORY_FILES):
    """Memory used by this container in GB, for the MAX_RAM_GB guard.

    ``psutil.virtual_memory()`` reads /proc/meminfo, the node's memory: the
    guard tripped on other pods' usage or never at all, and the OOM-kill came
    first.
    """
    for path in cgroup_files:
        try:
            with open(path) as f:
                return int(f.read().strip()) / 1e9
        except (OSError, ValueError):
            continue
    return psutil.Process().memory_info().rss / 1e9
