"""Settings that hold for every user, in the ``settings`` collection.

One document per group of settings, keyed by ``_id``. A missing document or
field is the default, so a database that never saw an admin change anything
behaves as shipped. The server writes them (the admin page) and the executor
reads them, hence this one place for the names.
"""

SETTINGS_COLLECTION = "settings"
DIGIT_BANK = "digit_bank"
# on unless an admin turns it off: the recogniser is retrained on these digits
DEFAULT_SAVE_VERIFIED_IMAGES = True


def save_verified_images(collection) -> bool:
    """Whether the digits a human confirmed are kept to retrain the recogniser.

    Args:
        collection: The ``settings`` collection.

    Returns:
        The admin's choice, or the default when none was made.
    """
    document = collection.find_one({"_id": DIGIT_BANK}) or {}
    return bool(document.get("save_verified_images", DEFAULT_SAVE_VERIFIED_IMAGES))


def set_save_verified_images(collection, value: bool) -> None:
    """Record the admin's choice for :func:`save_verified_images`.

    Args:
        collection: The ``settings`` collection.
        value: Keep the confirmed digits (True) or not.
    """
    collection.update_one(
        {"_id": DIGIT_BANK},
        {"$set": {"save_verified_images": bool(value)}},
        upsert=True,
    )
