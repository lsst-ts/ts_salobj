# This file is part of ts_salobj.
#
# Developed for the LSST Telescope and Site Systems.
# This product includes software developed by the LSST Project
# (https://www.lsst.org).
# See the COPYRIGHT file at the top-level directory of this distribution
# for details of code ownership.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

__all__ = ["AsyncS3Bucket"]

import asyncio
import io
import os
import re

import astropy.time
import astropy.units as u
import boto3
import botocore
import moto


class AsyncS3Bucket:
    """Asynchronous interface to an Amazon Web Services s3 bucket.

    Parameters
    ----------
    name : `str`
        Name of bucket. If using Amazon Web Services see
        <https://docs.aws.amazon.com/AmazonS3/latest/dev/UsingBucket.html>
        for details. In particular note that bucket names must be globally
        unique across all AWS accounts.
    domock : `bool`
        If True then start a mock S3 server.
        This is recommended for running in simulation mode.

    Attributes
    ----------
    service_resource : `boto3.resources.factory.s3.ServiceResource`
        The resource used to access the S3 service.
        Primarly provided for unit tests.
    name : `str`
        The bucket name
    bucket : `boto3.resources.s3.Bucket`
        The S3 bucket.

    Notes
    -----
    Reads the following `Environment Variables
    <https://ts-salobj.lsst.io/configuration.html#environment_variables>`_;
    follow the link for details:

    * **S3_ENDPOINT_URL**:  The endpoint URL, e.g. ``http://foo.bar:9000``.

    The format for bucket names, file keys, and ``largeFileEvent`` event URLs
    is described in `CAP 452 <https://jira.lsstcorp.org/browse/CAP-452>`_
    """

    def __init__(self, name, domock=False):
        self.mock = None
        if domock:
            self._start_mock(name)

        endpoint_url = os.environ.get("S3_ENDPOINT_URL", None)
        if not endpoint_url:
            endpoint_url = None  # Handle ""
        self.service_resource = boto3.resource("s3", endpoint_url=endpoint_url)
        self.name = name
        self.bucket = self.service_resource.Bucket(name)

    def _start_mock(self, name):
        """Start a mock S3 server with the specified bucket.
        """
        self.mock = moto.mock_s3()
        self.mock.start()

        # Set s3 authentication environment variables to bogus values
        # to avoid any danger of writing to a real s3 server.
        for env_var_name in (
            "AWS_ACCESS_KEY_ID",
            "AWS_SECRET_ACCESS_KEY",
            "AWS_SECURITY_TOKEN",
            "AWS_SESSION_TOKEN",
        ):
            os.environ[env_var_name] = "testing"

        # Make a bucket in mock s3 server so tests can upload to it.
        conn = boto3.resource("s3")
        conn.create_bucket(Bucket=name)

    def stop_mock(self):
        """Stop the mock s3 service, if running. A no-op if not running.
        """
        if self.mock is not None:
            self.mock.stop()
            self.mock = None

    @staticmethod
    def make_bucket_name(s3instance, s3category="LFA"):
        """Make an S3 bucket name.

        Parameters
        ----------
        salname : `str`
            SAL component name, e.g. ATPtg.
        salindexname : `str` or `None`
            For an indexed SAL component: a name associated with the SAL index,
            or just the index itself if there is no name.
            Specify `None` for a non-indexed SAL component.
            For example: "MT" for Main Telescope, "AT" for auxiliary telescope,
            or "ATBlue" for the AT Blue Fiber Spectrograph.
        s3instance : `str`
            S3 server instance. Typically "Summit", "Tucson" or "NCSA".
        s3category : `str` (optional)
            Category of S3 server. The default is "LFA",
            for the Large File Annex.

        Returns
        -------
        bucket_name : `str`
            The S3 bucket name in the format described below:

        Raises
        ------
        ValueError
            If one or more arguments does not meet the rules below
            or the resulting bucket name is longer than 63 characters.

        Notes
        -----
        The rules for all arguments are as follows:

        * Each argument must start and end with a letter or digit.
        * Each argument may only contain letters, digits, and ".".

        The returned bucket name is cast to lowercase (because S3 bucket names
        may not contain uppercase letters) and has format::

            rubinobs-{s3category}-{s3instance}]
        """
        valid_arg_regex = re.compile(r"^[a-z0-9][a-z0-9.]*$", flags=re.IGNORECASE)
        kwargs = dict(s3instance=s3instance, s3category=s3category)
        for argname, arg in kwargs.items():
            if valid_arg_regex.match(arg) is None:
                raise ValueError(f"{argname}={arg} invalid")
            if valid_arg_regex.match(arg[-1:]) is None:
                raise ValueError(f"{argname}={arg} invalid")
        bucket_name = f"rubinobs-{s3category}-{s3instance}".lower()
        if len(bucket_name) > 63:
            raise ValueError(
                f"Bucket name {bucket_name!r} too long: len={len(bucket_name)} > 63 chars"
            )
        return bucket_name

    @staticmethod
    def make_key(salname, salindexname, generator, date):
        """Make a key for an item of data.

        Parameters
        ----------
        salname : `str`
            SAL component name, e.g. ATPtg.
        salindexname : `str`, `int`, or `None`
            For an indexed SAL component: a name associated with the SAL index,
            or just the index itself if there is no name.
            Specify `None` for a non-indexed SAL component.
            For example: "MT" for Main Telescope, "AT" for auxiliary telescope,
            or "ATBlue" for the AT Blue Fiber Spectrograph.
        generator : `str`
            Dataset type.
        date : `astropy.time.Time`
            Date for the key.

        Returns
        -------
        key : `str`
            The key, as described below.

        Notes
        -----
        The returned key has format::

            {fullsalname}/{generator}/{yyyy}/{mm}/{dd}/
                {fullsalname}-{generator}-{tai_iso}

        where:

        * ``fullsalname`` = ``{salname}:{salindexname}`` if ``salindexname``,
          else ``salname``.
        * ``yyyy``, ``mm``, ``dd`` are the "observing day":
          the year, month and day at TAI date - 12 hours,
          with 4, 2, 2 digits, respectively.
          The "observing day" does change during nighttime observing
          at the summit.
        * ``tai_iso`` is the TAI date and time in ISO-8601 format,
          with a "T" between the date and time and a precision of milliseconds.

        The ISO date and observing date both the same precision (milliseconds)
        so that rounding is consistent.

        Note that the url field of the ``largeFileObjectAvailable`` event
        should have the format f"s3://{bucket}/{key}"
        """
        fullsalname = salname
        if salindexname:
            fullsalname += f":{salindexname}"
        taidate = astropy.time.Time(date, scale="tai", precision=3)
        shifted_isot = (taidate - 12 * u.hour).isot
        yyyy = shifted_isot[0:4]
        mm = shifted_isot[5:7]
        dd = shifted_isot[8:10]
        return f"{fullsalname}/{generator}/{yyyy}/{mm}/{dd}/{fullsalname}_{generator}_{taidate.isot}"

    async def upload(self, fileobj, key, callback=None):
        """Upload a file-like object to the bucket.

        Parameters
        ----------
        fileobj : file-like object
            File-like object that can be read as *binary* data.
        key : `str`
            Name to use for the file in the bucket.
        callback : callable (optional)
            Function to call with updates while writing. The function receives
            one argument: the number of bytes written. If the transfer is
            successful then it will always be called at least once,
            and the sum of the number of bytes for all calls will equal
            the size of the file.
            The callback function is called by ``S3.Bucket.upload_fileobj``.

        Notes
        -----
        To create a file-like object ``fileobj`` from an
        `astropy.io.fits.HDUList` named ``hdulist``::

            fileobj = io.BytesIO()
            hdulist.writeto(fileobj)
            fileobj.seek(0)
        """
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._sync_upload, fileobj, key, callback)

    async def download(self, key, callback=None):
        """Download a file-like object from the bucket.

        Parameters
        ----------
        key : `str`
            Name of the file in the bucket.
        callback : callable (optional)
            Function to call with updates while writing. The function receives
            one argument: the number of bytes read so far. If the transfer is
            successful then it will always be called at least once,
            and the sum of the number of bytes for all calls will equal
            the size of the file.

        Returns
        -------
        fileobj : `io.BytesIO`
            The downloaded data as a file-like object.

        Notes
        -----
        To convert a file-like object ``fileobj`` to an
        `astropy.io.fits.HDUList` named ``hdulist``::

            hdulist = astropy.io.fits.open(fileobj)

        The callback function is called by ``S3.Bucket.download_fileobj``.
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._sync_download, key, callback)

    async def exists(self, key):
        """Check if a specified file exists in the bucket.

        Parameters
        ----------
        key : `str`
            Name of the potential file in the bucket.
        """
        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(None, self._sync_size, key)
        except botocore.exceptions.ClientError as e:
            if e.response["Error"]["Code"] == "404":
                return False
            # Something went wrong; report it.
            raise
        return True

    async def size(self, key):
        """Get the size in bytes of a given file in the bucket.

        Parameters
        ----------
        key : `str`
            Name of the file in the bucket.
        """
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._sync_size, key)

    def _sync_upload(self, fileobj, key, callback):
        self.bucket.upload_fileobj(Fileobj=fileobj, Key=key, Callback=callback)

    def _sync_download(self, key, callback):
        fileobj = io.BytesIO()
        self.bucket.download_fileobj(Key=key, Fileobj=fileobj, Callback=callback)
        # Rewind the fileobj so read returns the data.
        fileobj.seek(0)
        return fileobj

    def _sync_size(self, key):
        return self.bucket.meta.client.head_object(Bucket=self.name, Key=key)[
            "ContentLength"
        ]
