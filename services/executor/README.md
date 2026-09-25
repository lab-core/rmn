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

## Digit bank

The digits a human confirmed, kept to retrain the model on the handwriting of
real students instead of MNIST alone (`python/process_copy/digit_bank.py`).

Every number the recogniser reads -- the matricule of a copy, a box of the
cover-page grade table, a grade drawn in ink -- is staged as its ordered digit
crops. When the job is finalised, each staged reading is matched with what the
humans settled (`tasks.finalize`): the matricule they validated, the grades
they confirmed in the correction screen. A reading whose crops cannot be
matched one for one with the confirmed number is dropped rather than guessed.

```
storage/digit_bank/
    staged/<job_id>/<document_index>/*.npz   # crops waiting for a confirmation
    samples/<digit>/<sha1 of the pixels>.png # the bank itself
    index.jsonl                              # one line per sample: what it is,
                                             # and what the model had read
```

Staged crops belong to the job and are deleted with it. A labelled sample
outlives it, which is why the promotion asks the teacher's `saveVerifiedImages`
(the switch in the user profile): **the reading is staged for everyone, the
bank only keeps what its owner allowed.** It is on by default, so a teacher
who never opens the profile screen contributes; turning it off stores a real
`false` and is honoured. Rows that predate the flag keep the default.

`digit_bank/samples` is in `rmn_common.storage.CORPUS_DIRS`: no cleanup, job
deletion or orphan sweep may remove it, and the monthly storage report counts
it on its own line, because it is the one part of the share that only grows.

**The samples are 64 x 64**, the thresholded mask the classifier sees, centred
with no margin. The model's input is 28 x 28, but the crops leave the page at
38-62 px for a handwritten matricule digit and 58-72 px for a printed grade
(measured on the recognition fixtures at 300 dpi), so storing 28 x 28 would
throw away three quarters of the pixels *and* freeze today's framing --
`config.digit_margins` is a training-time choice. From 64 any input the model
may want is a pad-and-downscale away (`digit_bank.view`); the other direction
invents detail.

```
python tools/build_digit_bank.py stats                 # samples per digit
python tools/build_digit_bank.py promote --all         # jobs validated but never finalised
python tools/build_digit_bank.py export --size 28 --margin 0.1 --out dataset_confirmed.npy
```

`export` writes the `(x, y)` pair `train.load_dataset` reads, so the bank mixes
into the training set beside MNIST.

This replaces `runtime.save_number_images`, deleted with it: that path filed
whole grade boxes under `storage/numbers/<digit>/`, for single-digit grades
only, and both of its call sites had been commented out for as long as they
existed. Anything `storage/numbers/` already holds is kept and still counted
(it is a corpus directory too); `unverified_numbers/` keeps its place in the
job layout so that what old trees hold still goes with its job.
