#!/usr/bin/env python3

import sys
import os
import argparse
import yaml
import tempfile
import Levenshtein
import shutil
from zipfile import ZipFile
from itertools import product
from pathlib import Path
from PIL import Image, ImageChops

META_FILE = "meta.yml"

IMG_DIFF_THRESHOLD = 0.07

SCAN_EXTENSIONS = [
    "*.jpg",
    "*.jpeg",
    "*.png",
    "*.webp",
]

def die(msg):
    print(msg)
    sys.exit(1)

def thumbnail(img):
    """Summarise an image into a 16 x 16 image."""
    return img.resize((16, 16))


def pixel_difference(img1, img2) -> float:
    """Find the difference between two images."""

    diff = ImageChops.difference(img1, img2)
    acc = 0
    width, height = diff.size
    for w, h in product(range(width), range(height)):
        r, g, b = diff.getpixel((w, h))
        acc += (r + g + b) / 3

    average_diff = acc / (width * height)
    normalised_diff = average_diff / 255
    return normalised_diff

def cleanup_dedups(path):
    """Find images in a directory and compare them all."""

    files = (list())
    for ext in SCAN_EXTENSIONS:
        files += list(Path(path).glob(ext))
    diffs = {}

    summaries = [(f, thumbnail(Image.open(f))) for f in files]
    for (f1, sum1), (f2, sum2) in product(summaries, repeat=2):
        key = tuple(sorted([str(f1), str(f2)]))
        if f1 == f2 or key in diffs:
            continue

        diff = pixel_difference(sum1, sum2)
        diffs[key] = diff

    print("    + Cleaning up duplicated pages")
    for key, diff in diffs.items():
        if diff < IMG_DIFF_THRESHOLD:
            for k in key:
                os.remove(k)

# main
if __name__ == "__main__":
    # parse command-line
    ps = argparse.ArgumentParser()
    ps.add_argument('-i', '--input', action='store', default=None, help='Input directory')
    ps.add_argument('-o', '--output', action='store', default=None, help='Output directory')
    ps.add_argument('-f', '--force', action='store_true', default=False, help='Generate ebook even if previously existing')
    ps.add_argument('-d', '--dedup', action='store_true', default=False, help='Try to detect and cleanup duplicated scan pages (e.g. ads)')
    args = ps.parse_args()

    if args.input == None:
        die("Missing input directory")

    if not os.path.isdir(args.input):
        die(f"Input directory '{args.input}' does not exists")

    if args.output == None:
        die("Missing output directory")
    os.makedirs(args.output, exist_ok=True)

    meta_file = f'{args.input}/{META_FILE}'
    if not os.path.isfile(meta_file):
        die(f"Input directory '{args.input}' metadata file does not exists")

    with open(meta_file, 'r') as f:
        meta = yaml.safe_load(f)

    title = meta.get('title')
    volumes = meta.get('volumes')
    print(f"Processing '{title}' with {len(volumes)} volumes ...")

    chapterdirs = [f for f in os.listdir(args.input) if os.path.isdir(os.path.join(args.input, f))]
    chapterdirs.sort()

    for v in volumes:
        name = v.get('name')
        chapters = v.get('chapters').split('-')
        if len(chapters) != 2:
            die(f"Incorrect chapters definition for volume name {name}")

        # retrieve chapters list
        chapters_range = range(int(chapters[0]), int(chapters[1]) + 1)

        # create volume temporary directory
        tmp_dir = tempfile.TemporaryDirectory()

        print(f"  - Processing volume {name} with {len(chapters_range)} chapters")
        # walkthrough chapters
        for c in chapters_range:
            candidatedirs = [cd for cd in chapterdirs if str(c) in cd]

            # find chapter's eligible directory
            score = 999
            chapterdir = None
            for cd in candidatedirs:
                dist_calc = Levenshtein.distance(str(c), cd)
                if dist_calc < score:
                    score = dist_calc
                    chapterdir = cd

            cdir = os.path.join(args.input, chapterdir)
            chapterfiles = [f for f in os.listdir(cdir) if os.path.isfile(os.path.join(cdir, f))]
            chapterfiles.sort()
            if len(chapterfiles) == 0:
                die(f"Chapter {c} seems to be empty. Missing scanned pages")

            # copy chapter files into temporary
            print(f"    + Copying chapter {c} scanned pages into temporary volume directory")
            for f in chapterfiles:
                ifile = os.path.join(cdir, f)
                oname = f'{c:04}-{f}'
                ofile = os.path.join(tmp_dir.name, oname)
                shutil.copyfile(ifile, ofile)

        # check for duplicate images (e.g. cover ads)
        if (args.dedup):
            cleanup_dedups(tmp_dir.name)

        # add all page files into CBZ/ZIP archive
        print("  - Creating temporary CBZ archive file")
        tmpfiles = [os.path.join(tmp_dir.name, f) for f in os.listdir(tmp_dir.name) if os.path.isfile(os.path.join(tmp_dir.name, f))]
        tmpfiles.sort()

        cbzfilename = f'{title} - {name}.cbz'
        cbzfile = os.path.join(tmp_dir.name, cbzfilename)
        with ZipFile(cbzfile, 'w') as zip:
            for f in tmpfiles:
                zip.write(f, os.path.basename(f))

        print("  - Converting CBZ archive into ePub one for Amazon Kindle")
        os.system(f'recbz --epub --bw --profile PW5 "{cbzfile}"')

        epubfilename = f'{title} - {name} [reCBZ].epub'
        print(f"Moving {epubfilename} into {args.output} directory ...")
        shutil.move(epubfilename, args.output)

        # cleanup volume temporary directory
        shutil.rmtree(tmp_dir.name)

sys.exit(0)
