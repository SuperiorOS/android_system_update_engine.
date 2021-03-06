#!/usr/bin/python2
#
# Copyright (C) 2015 The Android Open Source Project
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

"""Unit testing payload_info.py."""

from __future__ import print_function

import StringIO
import collections
import mock
import sys
import unittest

import payload_info
import update_payload

from contextlib import contextmanager

from update_payload import update_metadata_pb2

class FakePayloadError(Exception):
  """A generic error when using the FakePayload."""

class FakeOption(object):
  """Fake options object for testing."""

  def __init__(self, **kwargs):
    self.list_ops = False
    self.stats = False
    self.signatures = False
    for key, val in kwargs.iteritems():
      setattr(self, key, val)
    if not hasattr(self, 'payload_file'):
      self.payload_file = None

class FakeOp(object):
  """Fake manifest operation for testing."""

  def __init__(self, src_extents, dst_extents, op_type, **kwargs):
    self.src_extents = src_extents
    self.dst_extents = dst_extents
    self.type = op_type
    for key, val in kwargs.iteritems():
      setattr(self, key, val)

  def HasField(self, field):
    return hasattr(self, field)

class FakePartition(object):
  """Fake PartitionUpdate field for testing."""

  def __init__(self, partition_name, operations):
    self.partition_name = partition_name
    self.operations = operations

class FakeManifest(object):
  """Fake manifest for testing."""

  def __init__(self, major_version):
    FakeExtent = collections.namedtuple('FakeExtent',
                                        ['start_block', 'num_blocks'])
    self.install_operations = [FakeOp([],
                                      [FakeExtent(1, 1), FakeExtent(2, 2)],
                                      update_payload.common.OpType.REPLACE_BZ,
                                      dst_length=3*4096,
                                      data_offset=1,
                                      data_length=1)]
    self.kernel_install_operations = [FakeOp(
        [FakeExtent(1, 1)],
        [FakeExtent(x, x) for x in xrange(20)],
        update_payload.common.OpType.SOURCE_COPY,
        src_length=4096)]
    if major_version == payload_info.MAJOR_PAYLOAD_VERSION_BRILLO:
      self.partitions = [FakePartition('root', self.install_operations),
                         FakePartition('kernel',
                                       self.kernel_install_operations)]
      self.install_operations = self.kernel_install_operations = []
    self.block_size = 4096
    self.minor_version = 4
    FakePartInfo = collections.namedtuple('FakePartInfo', ['size'])
    self.old_rootfs_info = FakePartInfo(1 * 4096)
    self.old_kernel_info = FakePartInfo(2 * 4096)
    self.new_rootfs_info = FakePartInfo(3 * 4096)
    self.new_kernel_info = FakePartInfo(4 * 4096)
    self.signatures_offset = None
    self.signatures_size = None

  def HasField(self, field_name):
    """Fake HasField method based on the python members."""
    return hasattr(self, field_name) and getattr(self, field_name) is not None

class FakeHeader(object):
  """Fake payload header for testing."""

  def __init__(self, version, manifest_len, metadata_signature_len):
    self.version = version
    self.manifest_len = manifest_len
    self.metadata_signature_len = metadata_signature_len

  @property
  def size(self):
    return (20 if self.version == payload_info.MAJOR_PAYLOAD_VERSION_CHROMEOS
            else 24)

class FakePayload(object):
  """Fake payload for testing."""

  def __init__(self, major_version):
    self._header = FakeHeader(major_version, 222, 0)
    self.header = None
    self._manifest = FakeManifest(major_version)
    self.manifest = None

    self._blobs = {}
    self._payload_signatures = update_metadata_pb2.Signatures()
    self._metadata_signatures = update_metadata_pb2.Signatures()

  def Init(self):
    """Fake Init that sets header and manifest.

    Failing to call Init() will not make header and manifest available to the
    test.
    """
    self.header = self._header
    self.manifest = self._manifest

  def ReadDataBlob(self, offset, length):
    """Return the blob that should be present at the offset location"""
    if not offset in self._blobs:
      raise FakePayloadError('Requested blob at unknown offset %d' % offset)
    blob = self._blobs[offset]
    if len(blob) != length:
      raise FakePayloadError('Read blob with the wrong length (expect: %d, '
                             'actual: %d)' % (len(blob), length))
    return blob

  @staticmethod
  def _AddSignatureToProto(proto, **kwargs):
    """Add a new Signature element to the passed proto."""
    new_signature = proto.signatures.add()
    for key, val in kwargs.iteritems():
      setattr(new_signature, key, val)

  def AddPayloadSignature(self, **kwargs):
    self._AddSignatureToProto(self._payload_signatures, **kwargs)
    blob = self._payload_signatures.SerializeToString()
    self._manifest.signatures_offset = 1234
    self._manifest.signatures_size = len(blob)
    self._blobs[self._manifest.signatures_offset] = blob

  def AddMetadataSignature(self, **kwargs):
    self._AddSignatureToProto(self._metadata_signatures, **kwargs)
    if self._header.metadata_signature_len:
      del self._blobs[-self._header.metadata_signature_len]
    blob = self._metadata_signatures.SerializeToString()
    self._header.metadata_signature_len = len(blob)
    self._blobs[-len(blob)] = blob

class PayloadCommandTest(unittest.TestCase):
  """Test class for our PayloadCommand class."""

  @contextmanager
  def OutputCapturer(self):
    """A tool for capturing the sys.stdout"""
    stdout = sys.stdout
    try:
      sys.stdout = StringIO.StringIO()
      yield sys.stdout
    finally:
      sys.stdout = stdout

  def TestCommand(self, payload_cmd, payload, expected_out):
    """A tool for testing a payload command.

    It tests that a payload command which runs with a given payload produces a
    correct output.
    """
    with mock.patch.object(update_payload, 'Payload', return_value=payload), \
         self.OutputCapturer() as output:
      payload_cmd.Run()
    self.assertEquals(output.getvalue(), expected_out)

  def testDisplayValue(self):
    """Verify that DisplayValue prints what we expect."""
    with self.OutputCapturer() as output:
      payload_info.DisplayValue('key', 'value')
    self.assertEquals(output.getvalue(), 'key:                         value\n')

  def testRun(self):
    """Verify that Run parses and displays the payload like we expect."""
    payload_cmd = payload_info.PayloadCommand(FakeOption(action='show'))
    payload = FakePayload(payload_info.MAJOR_PAYLOAD_VERSION_CHROMEOS)
    expected_out = """Payload version:             1
Manifest length:             222
Number of operations:        1
Number of kernel ops:        1
Block size:                  4096
Minor version:               4
"""
    self.TestCommand(payload_cmd, payload, expected_out)

  def testListOpsOnVersion1(self):
    """Verify that the --list_ops option gives the correct output."""
    payload_cmd = payload_info.PayloadCommand(
        FakeOption(list_ops=True, action='show'))
    payload = FakePayload(payload_info.MAJOR_PAYLOAD_VERSION_CHROMEOS)
    expected_out = """Payload version:             1
Manifest length:             222
Number of operations:        1
Number of kernel ops:        1
Block size:                  4096
Minor version:               4

Install operations:
  0: REPLACE_BZ
    Data offset: 1
    Data length: 1
    Destination: 2 extents (3 blocks)
      (1,1) (2,2)
Kernel install operations:
  0: SOURCE_COPY
    Source: 1 extent (1 block)
      (1,1)
    Destination: 20 extents (190 blocks)
      (0,0) (1,1) (2,2) (3,3) (4,4) (5,5) (6,6) (7,7) (8,8) (9,9) (10,10)
      (11,11) (12,12) (13,13) (14,14) (15,15) (16,16) (17,17) (18,18) (19,19)
"""
    self.TestCommand(payload_cmd, payload, expected_out)

  def testListOpsOnVersion2(self):
    """Verify that the --list_ops option gives the correct output."""
    payload_cmd = payload_info.PayloadCommand(
        FakeOption(list_ops=True, action='show'))
    payload = FakePayload(payload_info.MAJOR_PAYLOAD_VERSION_BRILLO)
    expected_out = """Payload version:             2
Manifest length:             222
Number of partitions:        2
  Number of "root" ops:      1
  Number of "kernel" ops:    1
Block size:                  4096
Minor version:               4

root install operations:
  0: REPLACE_BZ
    Data offset: 1
    Data length: 1
    Destination: 2 extents (3 blocks)
      (1,1) (2,2)
kernel install operations:
  0: SOURCE_COPY
    Source: 1 extent (1 block)
      (1,1)
    Destination: 20 extents (190 blocks)
      (0,0) (1,1) (2,2) (3,3) (4,4) (5,5) (6,6) (7,7) (8,8) (9,9) (10,10)
      (11,11) (12,12) (13,13) (14,14) (15,15) (16,16) (17,17) (18,18) (19,19)
"""
    self.TestCommand(payload_cmd, payload, expected_out)

  def testStatsOnVersion1(self):
    """Verify that the --stats option works correctly."""
    payload_cmd = payload_info.PayloadCommand(
        FakeOption(stats=True, action='show'))
    payload = FakePayload(payload_info.MAJOR_PAYLOAD_VERSION_CHROMEOS)
    expected_out = """Payload version:             1
Manifest length:             222
Number of operations:        1
Number of kernel ops:        1
Block size:                  4096
Minor version:               4
Blocks read:                 11
Blocks written:              193
Seeks when writing:          18
"""
    self.TestCommand(payload_cmd, payload, expected_out)

  def testStatsOnVersion2(self):
    """Verify that the --stats option works correctly on version 2."""
    payload_cmd = payload_info.PayloadCommand(
        FakeOption(stats=True, action='show'))
    payload = FakePayload(payload_info.MAJOR_PAYLOAD_VERSION_BRILLO)
    expected_out = """Payload version:             2
Manifest length:             222
Number of partitions:        2
  Number of "root" ops:      1
  Number of "kernel" ops:    1
Block size:                  4096
Minor version:               4
Blocks read:                 11
Blocks written:              193
Seeks when writing:          18
"""
    self.TestCommand(payload_cmd, payload, expected_out)

  def testEmptySignatures(self):
    """Verify that the --signatures option works with unsigned payloads."""
    payload_cmd = payload_info.PayloadCommand(
        FakeOption(action='show', signatures=True))
    payload = FakePayload(payload_info.MAJOR_PAYLOAD_VERSION_CHROMEOS)
    expected_out = """Payload version:             1
Manifest length:             222
Number of operations:        1
Number of kernel ops:        1
Block size:                  4096
Minor version:               4
No metadata signatures stored in the payload
No payload signatures stored in the payload
"""
    self.TestCommand(payload_cmd, payload, expected_out)

  def testSignatures(self):
    """Verify that the --signatures option shows the present signatures."""
    payload_cmd = payload_info.PayloadCommand(
        FakeOption(action='show', signatures=True))
    payload = FakePayload(payload_info.MAJOR_PAYLOAD_VERSION_BRILLO)
    payload.AddPayloadSignature(version=1,
                                data='12345678abcdefgh\x00\x01\x02\x03')
    payload.AddPayloadSignature(data='I am a signature so access is yes.')
    payload.AddMetadataSignature(data='\x00\x0a\x0c')
    expected_out = """Payload version:             2
Manifest length:             222
Number of partitions:        2
  Number of "root" ops:      1
  Number of "kernel" ops:    1
Block size:                  4096
Minor version:               4
Metadata signatures blob:    file_offset=246 (7 bytes)
Metadata signatures: (1 entries)
  version=None, hex_data: (3 bytes)
    00 0a 0c                                        | ...
Payload signatures blob:     blob_offset=1234 (64 bytes)
Payload signatures: (2 entries)
  version=1, hex_data: (20 bytes)
    31 32 33 34 35 36 37 38 61 62 63 64 65 66 67 68 | 12345678abcdefgh
    00 01 02 03                                     | ....
  version=None, hex_data: (34 bytes)
    49 20 61 6d 20 61 20 73 69 67 6e 61 74 75 72 65 | I am a signature
    20 73 6f 20 61 63 63 65 73 73 20 69 73 20 79 65 |  so access is ye
    73 2e                                           | s.
"""
    self.TestCommand(payload_cmd, payload, expected_out)

if __name__ == '__main__':
  unittest.main()
