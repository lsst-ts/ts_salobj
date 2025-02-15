from __future__ import annotations

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
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

__all__ = ["MAX_SEQ_NUM", "SetWriteResult", "WriteTopic"]

import copy
import dataclasses
import typing
from collections.abc import Generator

import numpy as np
from lsst.ts import utils
from lsst.ts.xml import type_hints

from .base_topic import BaseTopic

if typing.TYPE_CHECKING:
    from ..sal_info import SalInfo

# Maximum value for the ``private_seqNum`` field of each topic,
# a 4 byte signed integer.
# For command topics this field is the command ID, and it must be unique
# for each command in order to avoid collisions (since there is only one
# ``ackcmd`` topic that is shared by all commands).
# For other topics its use is unspecified but it may prove handy to
# increment it (with wraparound) for each data point.
MAX_SEQ_NUM = (1 << 31) - 1


@dataclasses.dataclass
class SetWriteResult:
    """Result from set_write.

    Parameters
    ----------
    did_change
        Did the keywords change any values?
    was_written
        Was the message written?
    data
        The data, after applying keywords.
        This should be a copy, to avoid race conditions between this
        call and other code that alters the data.
    """

    did_change: bool
    was_written: bool
    data: type_hints.BaseMsgType


class WriteTopic(BaseTopic):
    r"""Base class for topics that are written.

    This includes  controller events, controller telemetry, remote commands
    and ``ackcmd`` writers.

    Parameters
    ----------
    salinfo : `SalInfo`
        SAL component information
    attr_name : `str`
        Topic name with attribute prefix. The prefix must be one of:
        ``cmd_``, ``evt_``, ``tel_``, or (only for the ackcmd topic) ``ack_``.
    min_seq_num : `int` or `None`, optional
        Minimum value for the ``private_seqNum`` field. The default is 1.
        If `None` then ``private_seqNum`` is not set; this is needed
        for the ackcmd writer, which sets the field itself.
    max_seq_num : `int`, optional
        Maximum value for ``private_seqNum``, inclusive.
        The default is the maximum allowed positive value
        (``private_seqNum`` is a 4-byte signed int).
        Ignored if ``min_seq_num`` is `None`.
    initial_seq_num : `int`, optional
        Initial sequence number; if `None` use min_seq_num.

    Attributes
    ----------
    isopen : `bool`
        Is this instance open? `True` until `close` or `basic_close` is called.
    default_force_output : `bool`
        Default value for the force_output argument of write.
    Plus the attributes of:
       `BaseTopic`
    """

    def __init__(
        self,
        *,
        salinfo: SalInfo,
        attr_name: str,
        min_seq_num: int | None = 1,
        max_seq_num: int = MAX_SEQ_NUM,
        initial_seq_num: int | None = None,
    ) -> None:
        super().__init__(salinfo=salinfo, attr_name=attr_name)
        # Events are usually only written if data has changed.
        # Commands, telemetry and ackcmd topics are usually always written.
        self.default_force_output = not attr_name.startswith("evt_")
        self.isopen = True
        self.min_seq_num = min_seq_num  # record for unit tests
        self.max_seq_num = max_seq_num
        if min_seq_num is None:
            self._seq_num_generator: Generator[int, None, None] | None = None
        else:
            self._seq_num_generator = utils.index_generator(
                imin=min_seq_num, imax=max_seq_num, i0=initial_seq_num
            )
        self._has_data = False
        self._data = self.DataType()
        # Record which field names are float, double or array of either,
        # to make it easy to compare float fields with nan equal.
        self._float_field_names = set()
        for name, value in vars(self._data).items():
            if isinstance(value, list):
                # In our SAL schemas arrays are fixed length
                # and must contain at least one element.
                elt = value[0]
            else:
                elt = value
            if isinstance(elt, float):
                self._float_field_names.add(name)

        salinfo.add_writer(self)

    @property
    def data(self) -> type_hints.BaseMsgType:
        """Internally cached message.

        Raises
        ------
        TypeError
            If ``data`` is not an instance of `DataType`

        Notes
        -----
        Do not assume the data will be constant. You can make a copy
        using ``copy.copy(data)``.
        """
        return self._data

    @data.setter
    def data(self, data: type_hints.BaseMsgType) -> None:
        if not isinstance(data, self.DataType):
            raise TypeError(f"data={data!r} must be an instance of {self.DataType}")
        self._data = data
        self._has_data = True

    @property
    def has_data(self) -> bool:
        """Has `data` ever been set?

        Note: a value of true means at least one field has been set,
        not that all fields have been set.
        """
        return self._has_data

    def basic_close(self) -> None:
        """A synchronous and possibly less thorough version of `close`.

        Intended for exit handlers and constructor error handlers.
        """
        if not self.isopen:
            return
        self.isopen = False

    async def close(self) -> None:
        """Shut down and release resources.

        Intended to be called by SalInfo.close(),
        since that tracks all topics.
        """
        self.basic_close()

    def set(self, **kwargs: typing.Any) -> bool:
        """Set one or more fields of message data ``self.data``.

        This is useful when accumulating data for a topic in different
        bits of code. Have each bit of code call `set` to set the fields
        it knows about. Have the last bit of code call `write` to set
        the remaining fields and write the completed message.

        If you have all the information for a topic in one place, it is simpler
        to call `set_write` to set all of the fields and write the message.

        Parameters
        ----------
        **kwargs : `dict` [`str`, ``any``]
            Dict of field name: new value for that field:

            * Any key whose value is `None` is checked for existence,
              but the value of the field is not changed.
            * If the field being set is an array then the value must be
              an array of the same length.

        Returns
        -------
        did_change : `bool`
            True if ``self.data`` was changed, or if this was the first call
            to `set`.

        Raises
        ------
        AttributeError
            If the topic does not have the specified field.
        ValueError
            If the field cannot be set to the specified value.

        Notes
        -----
        If one or more fields cannot be set, the message data may be
        partially updated.
        """
        # Always report did_change true if not self.has_data
        did_change = not self.has_data

        # Set a copy of the data, in case any of the data is invalid.
        data_dict = vars(self.data)
        unknown_fields = kwargs.keys() - data_dict.keys()
        if unknown_fields:
            raise AttributeError(
                f"{self.attr_name} has no fields {sorted(unknown_fields)}"
            )

        for field_name, value in kwargs.items():
            if value is None:
                if not hasattr(self.data, field_name):
                    raise AttributeError(f"{self.data} has no attribute {field_name}")
                # Keep the old value
                continue

            old_value = data_dict[field_name]
            if not did_change:
                try:
                    # array_equal works for sequences of all kinds,
                    # as well as strings and scalars
                    is_float = field_name in self._float_field_names
                    did_change |= not np.array_equal(
                        old_value,
                        value,
                        equal_nan=is_float,  # type: ignore
                    )
                except Exception as e:
                    raise TypeError(
                        f"Cannot set {self.attr_name}.{field_name}={value!r}; wrong type."
                    ) from e
            data_dict[field_name] = value
        # Check the data by creating a DataType, because no checking is done
        # when directly setting attributes of a dataclass.
        self.data = self.DataType(**data_dict)
        return did_change

    async def set_write(
        self, *, force_output: bool | None = None, **kwargs: typing.Any
    ) -> SetWriteResult:
        """Set zero or more fields of ``self.data`` and write if any field
        changed or if output forced.

        Parameters
        ----------
        force_output : `bool`, optional
            If True then write the event, even if no fields have changed.
            If None (the default), use the class default,
            which is True for all except ControllerEvent.
            (The default value is given by class constant
            ``default_force_output``).
        **kwargs : `dict` [`str`, ``any``]
            The remaining keyword arguments are
            field name = new value for that field.
            See `set` for more information about values.

        Returns
        -------
        result : `SetWriteResult`
            The resulting data and some flags.

        Notes
        -----
        The reason there are separate `set_write` and `write` methods is that
        `write` reliably writes the data, whereas the event version of
        `set_write` only writes the data if ``kwargs`` changes it,
        or if ``force_output`` is true.
        """
        did_change = self.set(**kwargs)
        if did_change:
            do_output = True
        else:
            do_output = (
                self.default_force_output if force_output is None else force_output
            )
        if do_output:
            data = await self.write()
        else:
            data = self.data
        return SetWriteResult(did_change=did_change, was_written=do_output, data=data)

    async def write(self) -> type_hints.BaseMsgType:
        """Write the current data and return a copy of the data written.

        Returns
        -------
        data : self.DataType
            The data that was written.
            This can be useful to avoid race conditions
            (as found in RemoteCommand).

        Raises
        ------
        RuntimeError
            If not running.
        """
        self.salinfo.assert_running()

        data = self._prepare_data_to_write()
        data_dict = vars(data)
        await self.salinfo.write_data(topic_info=self.topic_info, data_dict=data_dict)
        return data

    def _prepare_data_to_write(self) -> type_hints.BaseMsgType:
        """Prepare self.data to be written and return a copy of the result.

        Set the following fields:

        * private_sndStamp
        * private_origin
        * private_identity
        * private_seqNum, if a seq_num_generator is available
        * salIndex, if self.index is not 0

        Does not check self.salinfo.running
        """
        current_tai = utils.current_tai()
        self.data.private_sndStamp = current_tai
        self.data.private_efdStamp = utils.utc_from_tai_unix(current_tai)
        self.data.private_revCode = self.rev_code
        self.data.private_kafkaStamp = current_tai
        self.data.private_origin = self.salinfo.domain.origin
        self.data.private_identity = self.salinfo.identity
        if self._seq_num_generator is not None:
            self.data.private_seqNum = next(self._seq_num_generator)
        # If index is nonzero then set salIndex.
        # Otherwise the default of 0 is correct,
        # and the user can override it.
        if self.salinfo.index != 0:
            self.data.salIndex = self.salinfo.index
        return copy.copy(self.data)
