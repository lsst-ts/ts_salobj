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
import io
import os

import asynctest

import boto3
import moto

from lsst.ts import salobj


class AsyncS3BucketTest(asynctest.TestCase):
    def setUp(self):
        # Use moto.mock_s3 in "raw mode" because:
        # * @moto.mock_s3() does not work on async test methods.
        # * Even if it did, or if I used moto.mock_s3() as a context manager,
        #   I'd have to make the s3 bucket inside the test code.
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
        self.bucket_name = "async_bucket_test"
        conn = boto3.resource("s3")
        conn.create_bucket(Bucket=self.bucket_name)

        self.file_data = b"Data for the test case"
        self.key = "test_file"
        self.bucket = salobj.AsyncS3Bucket(self.bucket_name)
        self.fileobj = io.BytesIO(self.file_data)

    def tearDown(self):
        self.mock.stop()

    async def test_attributes(self):
        self.assertEqual(self.bucket.name, self.bucket_name)

    async def test_blank_s3_endpoint_url(self):
        os.environ["S3_ENDPOINT_URL"] = ""
        bucket = salobj.AsyncS3Bucket(self.bucket_name)
        self.assertIn("amazon", bucket.service_resource.meta.client.meta.endpoint_url)

    async def test_no_s3_endpoint_url(self):
        # Clear "S3_ENDPOINT_URL" if it exists.
        os.environ.pop("S3_ENDPOINT_URL", default=None)
        bucket = salobj.AsyncS3Bucket(self.bucket_name)
        self.assertIn("amazon", bucket.service_resource.meta.client.meta.endpoint_url)

    async def test_specified_s3_endpoint_url(self):
        endpoint_url = "http://foo.bar.edu:9000"
        os.environ["S3_ENDPOINT_URL"] = endpoint_url
        bucket = salobj.AsyncS3Bucket(self.bucket_name)
        self.assertEqual(
            bucket.service_resource.meta.client.meta.endpoint_url, endpoint_url
        )

    async def test_file_transfer(self):
        await self.bucket.upload(fileobj=self.fileobj, key=self.key)
        roundtrip_fileobj = await self.bucket.download(key=self.key)
        roundtrip_data = roundtrip_fileobj.read()
        self.assertEqual(self.file_data, roundtrip_data)

    async def test_exists(self):
        should_be_false = await self.bucket.exists(key="no_such_file")
        self.assertFalse(should_be_false)

        await self.bucket.upload(fileobj=self.fileobj, key=self.key)
        should_be_true = await self.bucket.exists(key=self.key)
        self.assertTrue(should_be_true)

    async def test_size(self):
        await self.bucket.upload(fileobj=self.fileobj, key=self.key)
        reported_size = await self.bucket.size(key=self.key)
        self.assertEqual(reported_size, len(self.file_data))

    async def test_callbacks(self):
        """Test callback functions with file transfers.
        """
        uploaded_nbytes = []
        downloaded_nbytes = []

        def upload_callback(nbytes):
            nonlocal uploaded_nbytes
            uploaded_nbytes.append(nbytes)

        def download_callback(nbytes):
            nonlocal downloaded_nbytes
            downloaded_nbytes.append(nbytes)

        await self.bucket.upload(
            fileobj=self.fileobj, key=self.key, callback=upload_callback
        )
        roundtrip_fileobj = await self.bucket.download(
            key=self.key, callback=download_callback
        )
        roundtrip_data = roundtrip_fileobj.getbuffer()
        self.assertEqual(self.file_data, roundtrip_data)
        self.assertGreaterEqual(len(uploaded_nbytes), 1)
        self.assertGreaterEqual(len(downloaded_nbytes), 1)
        self.assertEqual(sum(uploaded_nbytes), len(self.file_data))
        self.assertEqual(sum(downloaded_nbytes), len(self.file_data))
