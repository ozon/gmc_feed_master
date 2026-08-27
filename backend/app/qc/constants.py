from datetime import date

EXEMPT_TAXONOMY_IDS: frozenset[int] = frozenset({
    # Books
    784, 543541, 543542, 543543,
    # DVDs & Videos
    839, 543527, 543528, 543529,
    # Music & Sound Recordings
    855, 543522, 543523, 543524, 543525, 543526,
})

IMAGE_FORMATS: frozenset[str] = frozenset({
    "jpg", "jpeg", "webp", "png", "gif", "bmp", "tiff", "tif",
})

IMAGE_SIZE_ENFORCEMENT_DATE: date = date(2027, 1, 31)

IMAGE_FETCH_CAP_BYTES: int = 10 * 1024 * 1024  # 10 MB

IMAGE_CONCURRENCY: int = 8
