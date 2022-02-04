Configuration files for TestCsc unit tests.

This directory has a site-specific config file for site="test".
Also the file _init.yaml is intentionally incomplete and has
some fields that are overridden by _test.yaml.
This allows checking two things:
* Configuration is incomplete if LSST_SITE != "test"
* _test.yaml overrides _init.yaml
