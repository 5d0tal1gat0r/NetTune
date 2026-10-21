import pytest

from nettune.reading.transcription_service import data_url_mime


@pytest.mark.parametrize(
    "name,expected",
    [
        ("s.jpg", "image/jpeg"),
        ("s.jpeg", "image/jpeg"),
        ("s.JPG", "image/jpeg"),
        ("s.png", "image/png"),
        ("s.webp", "image/webp"),
        ("s.gif", "image/gif"),
    ],
)
def test_mime_for_natively_supported_formats(name, expected):
    assert data_url_mime(name) == expected


@pytest.mark.parametrize("name", ["s.tif", "s.tiff", "s.bmp", "s.TIFF"])
def test_formats_the_api_rejects_are_advertised_as_png(name):
    """They are converted before sending, so the data URL must say PNG."""
    assert data_url_mime(name) == "image/png"


def test_unknown_extension_defaults_to_jpeg():
    assert data_url_mime("scan.unknown") == "image/jpeg"
