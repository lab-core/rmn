"""Whether a copy's pdf carries what a grader wrote on it."""

import os

from pypdf import PdfReader

# Annotations that are not a grader's writing: links, form fields, and the
# popups that only hold another annotation's comment.
NOT_WRITING = {"/Link", "/Widget", "/Popup"}


def has_annotations(path):
    """True when a page of the pdf at ``path`` holds an annotation a grader
    could have written (ink, text, a shape, a stamp...). ``False`` for a file
    that is missing or cannot be read: nothing written can be seen on it.
    """
    if not os.path.isfile(path):
        return False
    try:
        reader = PdfReader(path)
        for page in reader.pages:
            for annotation in page.get("/Annots") or []:
                subtype = annotation.get_object().get("/Subtype")
                if subtype is not None and str(subtype) not in NOT_WRITING:
                    return True
    except Exception as e:  # a damaged copy must not break the listing
        print("has_annotations: cannot read", path, e)
    return False
