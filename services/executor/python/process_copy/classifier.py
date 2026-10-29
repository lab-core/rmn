"""The digit classifier at run time: the trained model exported to TFLite.

The CNN is trained with Keras (train.py) and exported once to
``digit_recognizer.tflite`` (export_tflite.py); the executor runs it with the
LiteRT interpreter, a 20 MB wheel, instead of shipping TensorFlow (1.5 GB) in
the image. The export is exact: the probabilities match the Keras model to
1e-7 on the same inputs.
"""

import os

import numpy as np

MODEL_FILE = "digit_recognizer.tflite"
# the executor root, where the model file lives next to job_executor.py
EXECUTOR_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class DigitClassifier:
    """Same ``predict`` signature as the Keras model, so the callers did not change."""

    def __init__(self, path):
        from ai_edge_litert.interpreter import Interpreter

        self._interpreter = Interpreter(model_path=str(path))
        self._input = self._interpreter.get_input_details()[0]
        self._output = self._interpreter.get_output_details()[0]
        self._batch_size = None

    def predict(self, batch, verbose=0):
        """Class probabilities, shape (n, 10), for ``batch`` of shape (n, 28, 28, 1)
        with float values in [0, 1]. The input tensor is resized when the batch
        size changes (the margins loop sends a fixed small batch)."""
        batch = np.ascontiguousarray(batch, dtype=np.float32)
        if batch.shape[0] != self._batch_size:
            self._interpreter.resize_tensor_input(self._input["index"], batch.shape)
            self._interpreter.allocate_tensors()
            self._batch_size = batch.shape[0]
        self._interpreter.set_tensor(self._input["index"], batch)
        self._interpreter.invoke()
        return np.array(self._interpreter.get_tensor(self._output["index"]))


SHIPPED_MODEL = os.path.join(EXECUTOR_DIR, MODEL_FILE)
# the model last announced in the log, so a job says once which one it reads with
_announced = None


def model_in_use(storage=None):
    """The model the executors run: the one an admin activated, else the shipped one.

    An admin activates a model retrained on the digit bank from the admin page
    (``rmn_common.digit_models``); the pointer lives in the storage, so it is
    read here, where the recogniser has no database handle.

    Returns:
        ``(path, run_id)``, ``run_id`` None for the shipped model.
    """
    from rmn_common import digit_models

    if storage is None:
        from process_copy.imaging import storage
    active = digit_models.active_model(storage)
    if active is None:
        return SHIPPED_MODEL, None
    return active["path"], active["run_id"]


def load_classifier(path=None):
    """The classifier, from ``path`` or from the model in use (:func:`model_in_use`)."""
    global _announced
    if path is None:
        path, run_id = model_in_use()
        if run_id != _announced:
            print("Digit model:", run_id or "shipped")
            _announced = run_id
    return DigitClassifier(path)
