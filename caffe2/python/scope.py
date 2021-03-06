## @package scope
# Module caffe2.python.scope
from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

import contextlib
import threading

from caffe2.proto import caffe2_pb2

# Python 2 and 3 compatibility: test if basestring exists
try:
    basestring  # NOQA
except NameError:
    # This is python3 so we define basestring.
    basestring = str

# The name scope and device scope when creating a new operator.
_NAMESCOPE_SEPARATOR = '/'

_threadlocal_scope = threading.local()


def CurrentNameScope():
    global _threadlocal_scope
    if not hasattr(_threadlocal_scope, "namescope"):
        _threadlocal_scope.namescope = ''
    return _threadlocal_scope.namescope


def CurrentDeviceScope():
    global _threadlocal_scope
    if not hasattr(_threadlocal_scope, "devicescope"):
        _threadlocal_scope.devicescope = None
    return _threadlocal_scope.devicescope


# NOTE: using NameScope is NOT thread-safe! (TODO t13621185)
@contextlib.contextmanager
def NameScope(prefix, reset=False):
    global _threadlocal_scope
    assert isinstance(prefix, basestring), \
        "NameScope takes in a string as its argument."
    old_scope = CurrentNameScope()
    prefix = prefix + _NAMESCOPE_SEPARATOR if prefix is not '' else ''
    if reset:
        _threadlocal_scope.namescope = prefix
    else:
        _threadlocal_scope.namescope = _threadlocal_scope.namescope + prefix
    yield
    assert _threadlocal_scope.namescope.endswith(prefix), \
        "The namescope variable is changed from outside NameScope() calls."
    _threadlocal_scope.namescope = old_scope


@contextlib.contextmanager
def DeviceScope(scope):
    assert isinstance(scope, caffe2_pb2.DeviceOption), \
        "DeviceScope takes in a caffe2_pb2.DeviceOption as its argument."
    global _threadlocal_scope
    old_scope = CurrentDeviceScope()
    _threadlocal_scope.devicescope = scope
    yield
    assert _threadlocal_scope.devicescope == scope, \
        "The device scope is changed from outside DeviceScope() calls."
    _threadlocal_scope.devicescope = old_scope
