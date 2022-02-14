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

__all__ = ["DefaultingValidator"]

import typing

import jsonschema


class DefaultingValidator:
    """A wrapper for jsonschema validators that applies default values.

    Parameters
    ----------
    schema : `dict`
        Schema against which to validate.
    ValidatorClass : ``jsonschema.IValidator``, optional
        jsonschema validator class, e.g. ``jsonschema.Draft7Validator``.

    Notes
    -----
    Default values are handled at most 2 levels deep in an object hierarchy.
    For deeper hierarchies, set the default at a higher level.
    For example::

        type: object
        properties:
          number1:
            type: number
            default: 1
          subdict1:
            type: object
            properties:
              number2:
                type: number
                default: 2
              subdict2:
                type: object
                properties:
                  number3:
                    type: number
                    # default is ignored this deep; set it at a higher level
                default:
                  number3: 3

    This class is not a ``jsonschema.IValidator`` but it contains two
    validators:

    * defaults_validator: a validator that sets default values in the
      data being validated
    * final_validator: a standard validator that does not alter
      the data being validated.
    """

    def __init__(
        self,
        schema: typing.Dict[str, typing.Any],
        # jsonschema 3.2 has no public base class for validators
        ValidatorClass: jsonschema.Draft7Validator = jsonschema.Draft7Validator,
    ) -> None:
        ValidatorClass.check_schema(schema)
        self.final_validator = ValidatorClass(schema=schema)

        validate_properties = ValidatorClass.VALIDATORS["properties"]

        def set_defaults(
            validator: jsonschema.Draft7Validator,
            properties: typing.Dict[str, typing.Any],
            instance: typing.Dict[str, typing.Any],
            schema: typing.Dict[str, typing.Any],
        ) -> typing.Generator[typing.Any, None, None]:
            """Wrap a jsonschema Validator so that it sets default values.

            Parameters
            ----------
            validator : ``jsonschema.IValidator``
                jsonschema validator.
            properties : `dict`
                The value of the property being validated within the instance
            instance : `dict`
                The item being checked and possibly set.
            schema : `dict`
                The schema being validated.

            Notes
            -----
            This code is based on https://python-jsonschema.readthedocs.io/
                en/stable/faq/#why-doesn-t-my-schema-
                s-default-property-set-the-default-on-my-instance
            but I added skip_properties to avoid infinite recursion
            """
            # most of these items cause infinite recursion if allowed through
            # and none are needed for setting defaults
            skip_properties = set(
                (
                    "additionalItems",
                    "additionalProperties",
                    "definitions",
                    "default",
                    "items",
                    "patternProperties",
                    "property",
                    "properties",
                    "readOnly",
                    "uniqueItems",
                )
            )
            for prop, subschema in properties.items():
                if not isinstance(subschema, dict):
                    continue
                if not isinstance(instance, dict):
                    continue
                if prop in skip_properties:
                    continue
                if "default" in subschema:
                    instance.setdefault(prop, subschema["default"])
                elif subschema.get("type") == "object" and "properties" in subschema:
                    # Handle defaults for one level deep sub-object.
                    subdefaults = {}
                    for subpropname, subpropvalue in subschema["properties"].items():
                        if "default" in subpropvalue:
                            subdefaults[subpropname] = subpropvalue["default"]
                    if subdefaults:
                        instance.setdefault(prop, subdefaults)

            for error in validate_properties(validator, properties, instance, schema):
                yield error

        WrappedValidator = jsonschema.validators.extend(
            ValidatorClass, {"properties": set_defaults}
        )
        WrappedValidator.check_schema(schema)
        self.defaults_validator = WrappedValidator(schema=schema)

    def validate(
        self, data_dict: typing.Optional[typing.Dict[str, typing.Any]]
    ) -> typing.Dict[str, typing.Any]:
        """Validate data.

        Set missing values based on defaults in the schema,
        then check the final result against the schema
        (in case any defaults are not valid).

        Parameters
        ----------
        data_dict : `dict` or `None`
            Data to validate. If None then an empty dict is used.

        Returns
        -------
        result : `dict`
            Validated data. A copy of data_dict with missing values
            that have defaults set to those defaults.

        Raises
        ------
        jsonschema.exceptions.ValidationError
            If the data does not match the schema.
        """
        if data_dict is None:
            result = {}
        elif type(data_dict) is not dict:
            raise jsonschema.exceptions.ValidationError(f"{data_dict} is not a dict")
        else:
            result = data_dict.copy()

        self.defaults_validator.validate(result)
        self.final_validator.validate(result)
        return result
