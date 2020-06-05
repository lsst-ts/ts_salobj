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
import astropy.time

from lsst.ts import salobj


class AsyncS3BucketTest(asynctest.TestCase):
    def setUp(self):
        self.bucket_name = "async_bucket_test"
        self.file_data = b"Data for the test case"
        self.key = "test_file"
        self.bucket = salobj.AsyncS3Bucket(self.bucket_name, create=True, domock=True)
        self.fileobj = io.BytesIO(self.file_data)

    def tearDown(self):
        self.bucket.stop_mock()

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


class AsyncS3BucketClassmethodTest(asynctest.TestCase):
    async def test_make_bucket_name_good(self):
        s3instance = "5TEST"
        expected_name = "rubinobs-lfa-5test"
        name = salobj.AsyncS3Bucket.make_bucket_name(s3instance=s3instance)
        self.assertEqual(name, expected_name)

        expected_name = "rubinobs-lfa-5test"
        name = salobj.AsyncS3Bucket.make_bucket_name(s3instance=s3instance)
        self.assertEqual(name, expected_name)

        s3category = "Other3"
        expected_name = "rubinobs-other3-5test"
        name = salobj.AsyncS3Bucket.make_bucket_name(
            s3instance=s3instance, s3category=s3category,
        )
        self.assertEqual(name, expected_name)

    async def test_make_bucket_name_bad(self):
        good_kwargs = dict(s3instance="TEST", s3category="other")
        expected_name = "rubinobs-other-test"
        name = salobj.AsyncS3Bucket.make_bucket_name(**good_kwargs)
        self.assertEqual(name, expected_name)

        for argname in good_kwargs:
            for badvalue in (
                ".foo",
                "foo.",
                "#foo",
                "fo#o",
                "@foo",
                "f@oo",
                "_foo",
                "fo_o",
            ):
                with self.subTest(argname=argname, badvalue=badvalue):
                    bad_kwargs = good_kwargs.copy()
                    bad_kwargs[argname] = badvalue
                    with self.assertRaises(ValueError):
                        salobj.AsyncS3Bucket.make_bucket_name(**bad_kwargs)

    async def test_make_key(self):
        # Try a date such that 12 hours earlier is just barely the previous day
        date = astropy.time.Time("2020-04-02T11:59:59.999", scale="tai")
        salname = "Foo"
        salindexname = "Blue"
        generator = "testFiberSpecBlue"
        key = salobj.AsyncS3Bucket.make_key(
            salname=salname, salindexname=salindexname, generator=generator, date=date
        )
        expected_key = (
            "Foo:Blue/testFiberSpecBlue/2020/04/01/"
            "Foo:Blue_testFiberSpecBlue_2020-04-02T11:59:59.999.dat"
        )
        self.assertEqual(key, expected_key)

        # Repeat the test with a date that rounds up to the next second.
        date = astropy.time.Time("2020-04-02T11:59:59.9999", scale="tai")
        key = salobj.AsyncS3Bucket.make_key(
            salname=salname, salindexname=salindexname, generator=generator, date=date
        )
        expected_key = (
            "Foo:Blue/testFiberSpecBlue/2020/04/02/"
            "Foo:Blue_testFiberSpecBlue_2020-04-02T12:00:00.000.dat"
        )
        self.assertEqual(key, expected_key)

        # Repeat the test with no sal index name
        key = salobj.AsyncS3Bucket.make_key(
            salname=salname, salindexname=None, generator=generator, date=date
        )
        expected_key = (
            "Foo/testFiberSpecBlue/2020/04/02/"
            "Foo_testFiberSpecBlue_2020-04-02T12:00:00.000.dat"
        )
        self.assertEqual(key, expected_key)

        # Repeat the test with an integer sal index name
        key = salobj.AsyncS3Bucket.make_key(
            salname=salname, salindexname=5, generator=generator, date=date
        )
        expected_key = (
            "Foo:5/testFiberSpecBlue/2020/04/02/"
            "Foo:5_testFiberSpecBlue_2020-04-02T12:00:00.000.dat"
        )
        self.assertEqual(key, expected_key)

        # Repeat the test with a specified value for "other"
        key = salobj.AsyncS3Bucket.make_key(
            salname=salname,
            salindexname=5,
            generator=generator,
            date=date,
            other="othertext",
        )
        expected_key = (
            "Foo:5/testFiberSpecBlue/2020/04/02/"
            "Foo:5_testFiberSpecBlue_othertext.dat"
        )
        self.assertEqual(key, expected_key)

        # Repeat the test with a specified value for "suffix"
        key = salobj.AsyncS3Bucket.make_key(
            salname=salname,
            salindexname=5,
            generator=generator,
            date=date,
            suffix="suffixtext",
        )
        expected_key = (
            "Foo:5/testFiberSpecBlue/2020/04/02/"
            "Foo:5_testFiberSpecBlue_2020-04-02T12:00:00.000suffixtext"
        )
        self.assertEqual(key, expected_key)
