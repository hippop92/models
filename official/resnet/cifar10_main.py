# Copyright 2017 The TensorFlow Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================
"""Runs a ResNet model on the CIFAR-10 dataset."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import argparse
import os
import sys

import tensorflow as tf

import resnet_model
import resnet_shared

_HEIGHT = 32
_WIDTH = 32
_NUM_CHANNELS = 3
_DEFAULT_IMAGE_SIZE = _HEIGHT * _WIDTH * _NUM_CHANNELS
_NUM_CLASSES = 10
_NUM_DATA_FILES = 5

# We use a weight decay of 0.0002, which performs better than the 0.0001 that
# was originally suggested.
_WEIGHT_DECAY = 2e-4
_MOMENTUM = 0.9

_NUM_IMAGES = {
    'train': 50000,
    'validation': 10000,
}


################################################################################
# Data processing
################################################################################
def record_dataset(filenames):
  """Returns an input pipeline Dataset from `filenames`."""
  record_bytes = _HEIGHT * _WIDTH * _NUM_CHANNELS + 1
  return tf.data.FixedLengthRecordDataset(filenames, record_bytes)


def get_filenames(is_training, data_dir):
  """Returns a list of filenames."""
  data_dir = os.path.join(data_dir, 'cifar-10-batches-bin')

  assert os.path.exists(data_dir), (
      'Run cifar10_download_and_extract.py first to download and extract the '
      'CIFAR-10 data.')

  if is_training:
    return [
        os.path.join(data_dir, 'data_batch_%d.bin' % i)
        for i in range(1, _NUM_DATA_FILES + 1)
    ]
  else:
    return [os.path.join(data_dir, 'test_batch.bin')]


def parse_record(raw_record):
  """Parse CIFAR-10 image and label from a raw record."""
  # Every record consists of a label followed by the image, with a fixed number
  # of bytes for each.
  label_bytes = 1
  record_bytes = label_bytes + _DEFAULT_IMAGE_SIZE

  # Convert bytes to a vector of uint8 that is record_bytes long.
  record_vector = tf.decode_raw(raw_record, tf.uint8)

  # The first byte represents the label, which we convert from uint8 to int32
  # and then to one-hot.
  label = tf.cast(record_vector[0], tf.int32)
  label = tf.one_hot(label, _NUM_CLASSES)

  # The remaining bytes after the label represent the image, which we reshape
  # from [depth * height * width] to [depth, height, width].
  depth_major = tf.reshape(record_vector[label_bytes:record_bytes],
                           [_NUM_CHANNELS, _HEIGHT, _WIDTH])

  # Convert from [depth, height, width] to [height, width, depth], and cast as
  # float32.
  image = tf.cast(tf.transpose(depth_major, [1, 2, 0]), tf.float32)

  return image, label


def preprocess_image(image, is_training):
  """Preprocess a single image of layout [height, width, depth]."""
  if is_training:
    # Resize the image to add four extra pixels on each side.
    image = tf.image.resize_image_with_crop_or_pad(image, _HEIGHT + 8,
                                                   _WIDTH + 8)

    # Randomly crop a [_HEIGHT, _WIDTH] section of the image.
    image = tf.random_crop(image, [_HEIGHT, _WIDTH, _NUM_CLASSES])

    # Randomly flip the image horizontally.
    image = tf.image.random_flip_left_right(image)

  # Subtract off the mean and divide by the variance of the pixels.
  image = tf.image.per_image_standardization(image)
  return image


def input_fn(is_training, data_dir, batch_size, num_epochs=1):
  """Input_fn using the tf.data input pipeline for CIFAR-10 dataset.

  Args:
    is_training: A boolean denoting whether the input is for training.
    data_dir: The directory containing the input data.
    batch_size: The number of samples per batch.
    num_epochs: The number of epochs to repeat the dataset.

  Returns:
    A tuple of images and labels.
  """
  dataset = record_dataset(get_filenames(is_training, data_dir))

  if is_training:
    # When choosing shuffle buffer sizes, larger sizes result in better
    # randomness, while smaller sizes have better performance. Because CIFAR-10
    # is a relatively small dataset, we choose to shuffle the full epoch.
    dataset = dataset.shuffle(buffer_size=_NUM_IMAGES['train'])

  dataset = dataset.map(parse_record)
  dataset = dataset.map(
      lambda image, label: (preprocess_image(image, is_training), label))

  dataset = dataset.prefetch(2 * batch_size)

  # We call repeat after shuffling, rather than before, to prevent separate
  # epochs from blending together.
  dataset = dataset.repeat(num_epochs)

  # Batch results by up to batch_size, and then fetch the tuple from the
  # iterator.
  dataset = dataset.batch(batch_size)
  iterator = dataset.make_one_shot_iterator()
  images, labels = iterator.get_next()

  return images, labels


################################################################################
# Running the model
################################################################################
class Cifar10Model(resnet_model.Model):

  def get_model_params(self):
    """These are the parameters that work for Cifar10 data.
    """
    return dict(
        num_classes=10,
        num_filters=16,
        kernel_size=3,
        first_pool_size=None,
        second_pool_size=8,
        block_fn=resnet_model.building_block,
        layers=self._get_layers(),
        stride_sizes=self._get_stride_sizes(),
        final_size=64)

  def _get_layers(self):
    if self.resnet_size % 6 != 2:
      raise ValueError('resnet_size must be 6n + 2:', resnet_size)

    num_blocks = (self.resnet_size - 2) // 6
    return [num_blocks] * 3

  def _get_stride_sizes(self):
    return [1, 1, 2, 2, 1]


def cifar10_model_fn(features, labels, mode, params):
  """Model function for CIFAR-10."""
  features = tf.reshape(features, [-1, _HEIGHT, _WIDTH, _NUM_CHANNELS])

  train_params = dict(
      batch_denom=128,
      epochs=[100, 150, 200],
      learning_rates=[1, 0.1, 0.01, 1e-3],
      weight_decay=_WEIGHT_DECAY,
      train_images=_NUM_IMAGES['train'],
      momentum=_MOMENTUM)

  params.update(train_params)

  return resnet_shared.resnet_model_fn(features, labels, mode, params,
                                       Cifar10Model)


def main(unused_argv):
  resnet_shared.resnet_main(FLAGS, cifar10_model_fn, input_fn)


if __name__ == '__main__':
  tf.logging.set_verbosity(tf.logging.INFO)

  parser = resnet_shared.ResnetArgParser()
  FLAGS, unparsed = parser.parse_known_args()
  tf.app.run(argv=[sys.argv[0]] + unparsed)
