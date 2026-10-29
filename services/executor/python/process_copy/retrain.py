"""Fine-tune the shipped digit model on the digit bank.

Runs in the trainer image only (``Dockerfile.trainer``): it needs TensorFlow,
which the executor image leaves out. The trainer worker (``trainer.py``)
calls :func:`fine_tune` and :func:`convert`; the result is scored by
:mod:`process_copy.bank_eval` like any other model.

Every run starts again from the shipped model (``digit_recognizer.h5``) with
the whole training part of the bank, rather than from the model in use: a run
then depends on the bank alone, and retraining a retrained model cannot drift
away from the original one step after step.

The bank is small next to what the model learnt from, and the model must keep
reading what the bank holds little of: each epoch mixes the bank, framed as the
recogniser frames it and slightly distorted, with a replay of MNIST.
"""

from __future__ import annotations

from typing import Any, Callable, Optional, Tuple

import cv2
import numpy as np

from process_copy.bank_eval import Bank, framed
from process_copy.config import digit_margins

EPOCHS = 10
# a tenth of Adam's default: the model is adjusted, not learnt again
LEARNING_RATE = 1e-4
BATCH_SIZE = 128
# MNIST images replayed with the bank at every run
MNIST_REPLAY = 30000
# distorted copies of each framed bank digit, on top of the digit itself
AUGMENTED = 4

Progress = Callable[[int, int, dict], None]


def mnist() -> Tuple[Tuple[np.ndarray, np.ndarray], Tuple[np.ndarray, np.ndarray]]:
    """MNIST, from Keras' cache (the trainer image downloads it when built)."""
    from keras.datasets import mnist as dataset

    return dataset.load_data()


def distort(image: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """A 28 x 28 digit slightly rotated, scaled and shifted, as another hand would."""
    angle = rng.uniform(-10, 10)
    scale = rng.uniform(0.9, 1.1)
    matrix = cv2.getRotationMatrix2D((13.5, 13.5), angle, scale)
    matrix[:, 2] += rng.uniform(-1.5, 1.5, size=2)
    return cv2.warpAffine(
        image, matrix, (28, 28), flags=cv2.INTER_LINEAR, borderValue=0
    )


def bank_images(bank: Bank, seed: int = 0) -> Tuple[np.ndarray, np.ndarray]:
    """The training images the bank gives: every framing, and its distortions.

    Returns:
        ``(x, y)``, ``x`` of shape ``(n, 28, 28)`` uint8.
    """
    if not len(bank):
        return np.empty((0, 28, 28), dtype="uint8"), np.array([], dtype="int")
    rng = np.random.default_rng(seed)
    images = framed(bank.x, digit_margins)
    labels = np.repeat(bank.y, len(digit_margins))
    variants = [images] + [
        np.stack([distort(img, rng) for img in images]) for _ in range(AUGMENTED)
    ]
    return np.concatenate(variants), np.tile(labels, AUGMENTED + 1)


def training_set(
    bank: Bank, replay: Tuple[np.ndarray, np.ndarray], seed: int = 0
) -> Tuple[np.ndarray, np.ndarray]:
    """The bank's images with :data:`MNIST_REPLAY` MNIST images, shuffled."""
    rng = np.random.default_rng(seed)
    x_bank, y_bank = bank_images(bank, seed)
    x_mnist, y_mnist = replay
    keep = rng.permutation(len(y_mnist))[:MNIST_REPLAY]
    x = np.concatenate([x_bank, x_mnist[keep]])
    y = np.concatenate([y_bank, y_mnist[keep]])
    order = rng.permutation(len(y))
    return x[order], y[order]


def fine_tune(
    base_path: str,
    x: np.ndarray,
    y: np.ndarray,
    epochs: Optional[int] = None,
    on_epoch: Optional[Progress] = None,
    seed: int = 0,
) -> Any:
    """The model at ``base_path`` trained some more on ``(x, y)``.

    Args:
        base_path: The Keras model to start from.
        x: ``(n, 28, 28)`` uint8 images.
        y: ``(n,)`` digits.
        epochs: Passes over ``(x, y)``, :data:`EPOCHS` by default.
        on_epoch: Called after each pass with ``(epoch, epochs, logs)``.
        seed: Seeds Keras, so a run on the same bank gives the same model.

    Returns:
        The trained Keras model.
    """
    import keras

    epochs = epochs or EPOCHS
    keras.utils.set_random_seed(seed)
    model = keras.models.load_model(base_path)
    model.compile(
        optimizer=keras.optimizers.Adam(learning_rate=LEARNING_RATE),
        loss="categorical_crossentropy",
        metrics=["accuracy"],
    )
    callbacks = []
    if on_epoch is not None:
        callbacks.append(
            keras.callbacks.LambdaCallback(
                on_epoch_end=lambda epoch, logs: on_epoch(
                    epoch + 1, epochs, dict(logs or {})
                )
            )
        )
    model.fit(
        x.reshape(-1, 28, 28, 1).astype("float32") / 255,
        keras.utils.to_categorical(y, 10),
        epochs=epochs,
        batch_size=BATCH_SIZE,
        callbacks=callbacks,
        verbose=2,
    )
    return model


def convert(model: Any) -> bytes:
    """The model as the TFLite file the executors run."""
    import tensorflow as tf

    return tf.lite.TFLiteConverter.from_keras_model(model).convert()
