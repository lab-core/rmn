"""Export the trained Keras model to the TFLite file the executor runs.

Development only (needs tensorflow, see requirements-train.txt):

    cd services/executor
    python -m python.process_copy.export_tflite            # digit_recognizer.h5 -> .tflite
    python -m python.process_copy.export_tflite in.h5 out.tflite

Run it after every training (train.py); the image ships only the .tflite.
"""

import sys

import numpy as np


def export(h5_path, tflite_path):
    import tensorflow as tf
    from keras.models import load_model

    model = load_model(h5_path)
    data = tf.lite.TFLiteConverter.from_keras_model(model).convert()
    with open(tflite_path, "wb") as f:
        f.write(data)

    # the export must be exact: compare both models on random inputs
    from .classifier import DigitClassifier

    lite = DigitClassifier(tflite_path)
    x = np.random.default_rng(0).random((4, 28, 28, 1), dtype=np.float32)
    diff = float(np.abs(model.predict(x, verbose=0) - lite.predict(x)).max())
    print(f"{tflite_path}: {len(data)} bytes, max deviation from the Keras model {diff:.2e}")
    if diff > 1e-5:
        raise SystemExit("the exported model deviates from the Keras model")


if __name__ == "__main__":
    args = sys.argv[1:]
    export(args[0] if args else "digit_recognizer.h5", args[1] if len(args) > 1 else "digit_recognizer.tflite")
