# This file is part of ts_salobj.
#
# Developed for the Rubin Observatory Telescope and Site System.
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

__all__ = ["CONFIG_SCHEMA"]

import typing
import yaml


# Config schema for TestCSC
CONFIG_SCHEMA: typing.Dict[str, typing.Any] = yaml.safe_load(
    """
$schema: http://json-schema.org/draft-07/schema#
$id: https://github.com/lsst-ts/ts_salobj/blob/main/python/lsst/ts/salobj/config_schema.py
# title must end with one or more spaces followed by the schema version, which must begin with "v"
title: Test v2
description: Configuration for the TestCsc
type: object
properties:
  string0:
    type: string
  bool0:
    type: boolean
  int0:
    type: integer
  float0:
    type: number
  intarr0:
    type: array
    items:
      type: integer
  multi_type:
    anyOf:
      - type: integer
        minimum: 1
      - type: string
      - type: "null"

required: [string0, bool0, int0, float0, intarr0, multi_type]
additionalProperties: false
"""
)
