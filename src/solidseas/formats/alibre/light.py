"""``LIGHT_CONFIGURATION_DATA``: the active configuration's name and the part's colour
(provisional, ``docs/formats/alibre.md``).

Four bytes (zero in every sample), the configuration's name (a big-endian 16-bit
length and its bytes), four more bytes and one byte (meaning unknown), then the
part's colour as red, green, blue and alpha bytes. The colour equals the one in
``MESH_DATA`` and the ACIS body's ``rgb_color`` attribute in the samples; an
assembly stores all zeros there, read as no colour.
"""

import struct
from dataclasses import dataclass

from ...errors import SldFormatError

Color = tuple[float, float, float, float]


@dataclass(frozen=True)
class LightConfiguration:
    configuration: str | None
    color: Color | None


def read(data: bytes) -> LightConfiguration:
    if len(data) < 6:
        raise SldFormatError(
            "LIGHT_CONFIGURATION_DATA is too short", detail={"stream": "LIGHT_CONFIGURATION_DATA"}
        )
    (n,) = struct.unpack_from(">H", data, 4)
    if 6 + n > len(data):
        raise SldFormatError(
            "LIGHT_CONFIGURATION_DATA's name runs past the stream",
            detail={"stream": "LIGHT_CONFIGURATION_DATA"},
        )
    name = data[6 : 6 + n].decode("utf-8", "replace") or None
    color = None
    at = 6 + n + 5
    if at + 4 <= len(data):
        r, g, b, a = data[at : at + 4]
        if a:
            color = (r / 255.0, g / 255.0, b / 255.0, a / 255.0)
    return LightConfiguration(name, color)


__all__ = ["LightConfiguration", "read"]
