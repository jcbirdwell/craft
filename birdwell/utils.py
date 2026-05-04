import re
from time import time
from datetime import timedelta
from re import Pattern
from datetime import datetime, UTC
import json
from inspect import isfunction

from pydantic import BaseModel


def subkey(obj: dict, *keys):
    """produces a version of the obj with only the specified keys"""
    return {k: obj[k] for k in obj if k in keys}



def regrouper(regex: Pattern | str, single=None, null_miss=False):
    cmp = re.compile(regex)
    cnt = cmp.groups
    search = cmp.search


    if single is not None:
        if cnt < single:
            ValueError(f'single target is out of bounds. supplied regex has [{cnt}] groups')

        def search_groups(s: str):
            if m := search(s):
                return m.group(single)
            return None

    else:
        # pregen the null return tuple
        if null_miss:
            _nulled_return = None
        else:
            _nulled_return = tuple(cnt * [None])

        def search_groups(s: str):
            if m := search(s):
                return m.groups()
            return _nulled_return

    return search_groups


def age(dt: datetime | int):
    if isinstance(dt, int):
        return int(time() - dt)

    return datetime.now(dt.tzinfo) - dt


def stale(dt: datetime | None | int, max_age: timedelta | int):
    if not dt:
        return True

    if isinstance(max_age, int):
        max_age = timedelta(seconds=max_age)


    return age(dt) > max_age




class DumpDict(dict):
    def dump(self):
        return list(self.values())


class FlexEncoder(json.JSONEncoder):
    def encode(self, o, as_vals=False, sort=False):
        if o is None:
            return None

        if as_vals:
            if isinstance(o, DumpDict):
                o = o.dump()
            else:
                o = list(o.values())
            if sort:
                o = sorted(o, key=lambda kv: kv[0])
        return super().encode(o)

    def default(self, o):

        if isinstance(o, datetime):
            return o.astimezone(UTC).isoformat()
        elif isinstance(o, set):
            return list(o)
        elif isinstance(o, BaseModel):
            return o.model_dump()
        elif isfunction(o):
            return None
        elif isinstance(o, Path):
            return str(o)
        else:
            return super().default(o)


from pathlib import Path
from zipfile import ZipInfo, ZIP_DEFLATED, ZipFile
from io import BytesIO
from hashlib import sha256


class MemoryZip:
    def __init__(
            self,
            out_dir: Path,
            file_prefix: str,
            finalize_on_close=True,
            compression=ZIP_DEFLATED,
            fixed=True
    ):
        """
        handle the writing to and of a zipfile in memory for faster content sha256 hashing

        Parameters
        ----------
        out_dir : output directory of finalized result path
        file_prefix : file prefix out result
        finalize_on_close : perform file finalization on close instead of just closing handles)
        compression : zip compression used
        """
        self.zip: ZipFile | None = None
        self.out_dir = out_dir
        self.file_prefix = file_prefix
        self.mem: BytesIO | None = None
        self.compression = compression
        self.finalize_on_close = finalize_on_close
        self.fixed = fixed

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.finalize_on_close:
            # automatic finalizing for when result path isn't used directly
            self.finalize()
        else:
            # abandoned or already manually finalized for result usage
            self.close()


    def open(self, override=False):
        if self.mem or self.zip:
            if not override:
                raise Exception('already open')
            # otherwise we dump for recreation
            self.close()

        self.mem = BytesIO()
        self.zip = ZipFile(self.mem, mode='w', compression=self.compression)

    def close(self):
        """close handles without finalizing"""
        if self.zip:
            self.zip.close()
            self.zip = None
        if self.mem:
            self.mem.close()
            self.mem = None


    def finalize(self):
        # guard
        if not self.zip or not self.mem:
            raise Exception('not open, nothing to finalize')

        # finalize zip and null immediately to lock finalizing
        self.zip.close()
        self.zip = None

        temp_path = self.out_dir.joinpath(f'{self.file_prefix}.zip.part')
        self.mem.seek(0)
        sha = sha256()
        result = None
        try:
            with temp_path.open('wb') as df:
                # read in chunks to reduce footprint... a little
                while True:
                    chunk = self.mem.read(65536)
                    if not chunk: break
                    sha.update(chunk)
                    df.write(chunk)

                chunk = None # dump
                sha_hex = sha.hexdigest()

            # now that we have sha_hex and file written we can finalize the name
            result = temp_path.rename(self.out_dir.joinpath(f'{self.file_prefix}-{sha_hex}.zip'))

        # finally block to prevent leaving the handle open
        # on an io error
        finally:
            # dump partial temp_file if it never made it to rename stage
            if temp_path.exists():
                temp_path.unlink()

            # close and give to gc
            self.mem.close()
            self.mem = None

        return result

    def write(self, file: str, data: bytes | str):
        if not self.zip:
            raise Exception('zip must be initialized before writing')
        if self.fixed:
            zp = ZipInfo(file, date_time=(2000, 3, 1, 0, 0, 0)) # march 1, 2000
        else:
            zp = file
        self.zip.writestr(zp, data)

