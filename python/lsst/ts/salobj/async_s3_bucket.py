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

import boto3
import botocore


class AsyncS3Bucket:
    """Asynchronous interface to Amazon Web Services s3 buckets.

    Parameters
    ----------
    name : `str`
        Name of bucket. If using Amazon Web Services see
        <https://docs.aws.amazon.com/AmazonS3/latest/dev/UsingBucket.html>
        for details. In particular note that bucket names must be globally
        unique across all AWS accounts.

    Notes
    -----
    Reads the following `Environment Variables
    <https://ts-salobj.lsst.io/configuration.html#environment_variables>`_;
    follow the link for details:

    * **S3_ENDPOINT_URL**:  The endpoint URL, e.g. ``http://foo.bar:9000``.

    **Attributes**

    * **service_resource** : `boto3.resources.factory.s3.ServiceResource`
        The resource used to access the S3 service.
        Primarly provided for unit tests.
    * **name** : `str`
        The bucket name
    * **bucket** : `boto3.resources.s3.Bucket`
        The S3 bucket.
    """

    def __init__(self, name):
        endpoint_url = os.environ.get("S3_ENDPOINT_URL", None)
        if not endpoint_url:
            endpoint_url = None  # Handle ""
        self.service_resource = boto3.resource("s3", endpoint_url=endpoint_url)
        self.name = name
        self.bucket = self.service_resource.Bucket(name)

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

        Notes
        -----
        To create a file-like object ``fileobj`` from an
        `astropy.io.fits.HDUList` named ``hdulist``:

            fileobj = io.BytesIO()
            hdulist.writeto(fileobj)
            fileobj.seek(0)

        The callback function is called by ``S3.Bucket.upload_fileobj``.
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
        `astropy.io.fits.HDUList` named ``hdulist``:

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
