"""The settings every user shares."""

from rmn_common.settings import (
    DIGIT_BANK,
    save_verified_images,
    set_save_verified_images,
)


class FakeCollection:
    """Just enough of a Mongo collection: documents by _id."""

    def __init__(self):
        self.documents = {}

    def find_one(self, query):
        return self.documents.get(query["_id"])

    def update_one(self, query, update, upsert=False):
        document = self.documents.get(query["_id"])
        if document is None:
            assert upsert
            document = self.documents[query["_id"]] = {"_id": query["_id"]}
        document.update(update["$set"])


def test_the_digits_are_kept_until_an_admin_says_otherwise():
    settings = FakeCollection()
    assert save_verified_images(settings) is True
    settings.documents[DIGIT_BANK] = {"_id": DIGIT_BANK}  # a group without the field
    assert save_verified_images(settings) is True


def test_the_admin_choice_is_stored_and_read_back():
    settings = FakeCollection()
    set_save_verified_images(settings, False)
    assert save_verified_images(settings) is False
    set_save_verified_images(settings, 1)
    assert settings.documents[DIGIT_BANK]["save_verified_images"] is True
