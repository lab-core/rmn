# process-copy
Process copies: handle moodle files and grades, extract grades.

## Digit model

`digit_recognizer.tflite` is the CNN that reads handwritten grades and matricules,
run at execution time by the LiteRT interpreter (`python/process_copy/classifier.py`,
a 20 MB wheel). The image does not ship TensorFlow.

The model is trained with Keras and exported once:

```
pip install -r requirements-train.txt          # tensorflow + keras, development only
python -m python.process_copy.train ...        # writes digit_recognizer_<name>.h5
python -m python.process_copy.export_tflite digit_recognizer.h5 digit_recognizer.tflite
```

The export checks that the TFLite model matches the Keras one on random inputs (it is
exact, about 1e-7). `digit_recognizer.h5` stays in the repository for retraining and is
excluded from the image. The recognition fixtures (`tests/test_recognition.py`) read the
same digits from real scans and will flag any drift.
