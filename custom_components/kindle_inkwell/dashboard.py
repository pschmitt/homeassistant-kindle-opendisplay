"""Render and send a room and vessel dashboard through OpenDisplay."""

import asyncio
import io
import logging
import re
from uuid import uuid4

import aiohttp
import voluptuous as vol
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.network import NoURLAvailableError, get_url
from PIL import Image, ImageDraw, ImageFont, ImageOps, UnidentifiedImageError

from .const import DOMAIN

IMAGES = f"{DOMAIN}_dashboard_images"
LOG = logging.getLogger(__name__)
PHOTO_PATH = re.compile(r"/api/ais_vessel_tracker/photo/[a-zA-Z0-9_-]+/[0-9]+")
ROOM = vol.Schema(
    {
        vol.Required("name"): cv.string,
        vol.Required("temperature"): cv.entity_id,
        vol.Required("co2"): cv.entity_id,
    }
)
SCHEMA = vol.Schema(
    {
        vol.Required("device_id"): cv.string,
        vol.Required("rooms"): vol.All([ROOM], vol.Length(min=1, max=3)),
        vol.Required("outdoor_temperature"): cv.entity_id,
        vol.Required("weather"): cv.entity_id,
        vol.Required("vessel"): cv.entity_id,
    }
)


def _value(state, decimals, unit):
    try:
        return f"{float(state.state):.{decimals}f} {unit}"
    except (AttributeError, ValueError):
        return "Unavailable"


def _render(rooms, outdoor, weather, vessel, photo, credit):
    image = Image.new("L", (1072, 1448), 255)
    draw = ImageDraw.Draw(image)

    def label(x, y, text, size, *, width=950, fill=0):
        font = ImageFont.load_default(size=size)
        while draw.textlength(text, font=font) > width and size > 18:
            size -= 2
            font = ImageFont.load_default(size=size)
        if draw.textlength(text, font=font) > width:
            while draw.textlength(text + "…", font=font) > width:
                text = text[:-1]
            text += "…"
        draw.text((x, y), text, font=font, fill=fill)

    label(54, 42, "Home", 78)
    draw.rectangle((54, 155, 1018, 327), fill=0)
    label(78, 174, "Outside", 31, fill=255)
    label(78, 217, outdoor, 57, width=420, fill=255)
    label(553, 174, "Weather", 31, fill=255)
    label(553, 226, weather, 43, width=435, fill=255)

    label(54, 362, "Room", 29)
    label(442, 362, "Temperature", 29)
    label(755, 362, "CO₂", 29)
    for index, (name, temperature, co2) in enumerate(rooms):
        y = 414 + index * 106
        draw.line((54, y, 1018, y), fill=0, width=3)
        label(54, y + 26, name, 42, width=365)
        label(442, y + 26, temperature, 38, width=285)
        label(755, y + 26, co2, 38, width=260)

    label(54, 755, "Last vessel", 29)
    label(54, 799, vessel, 54, width=964)
    box = (964, 458)
    if photo:
        try:
            with Image.open(io.BytesIO(photo)) as source:
                cropped = ImageOps.fit(
                    ImageOps.exif_transpose(source).convert("L"), (482, 229)
                )
                dithered = cropped.convert("1").resize(box, Image.Resampling.NEAREST)
                image.paste(dithered, (54, 890))
        except (OSError, UnidentifiedImageError, Image.DecompressionBombError):
            photo = None
    if not photo:
        draw.rectangle((54, 890, 1018, 1348), outline=0, width=3)
        label(84, 1088, "Vessel photo unavailable", 36)
    elif credit:
        label(54, 1370, f"Photo: {credit}", 25, width=964)

    output = io.BytesIO()
    image.convert("1").save(output, format="PNG")
    return output.getvalue()


async def _photo(hass, path):
    if not isinstance(path, str) or not PHOTO_PATH.fullmatch(path):
        return None
    try:
        base = get_url(hass, allow_external=False)
        async with (
            asyncio.timeout(10),
            async_get_clientsession(hass).get(
                base + path, allow_redirects=False
            ) as response,
        ):
            if response.status != 200:
                return None
            data = bytearray()
            async for chunk in response.content.iter_chunked(65536):
                data.extend(chunk)
                if len(data) > 5 * 1024 * 1024:
                    return None
            return bytes(data)
    except (NoURLAvailableError, OSError, TimeoutError, aiohttp.ClientError):
        LOG.debug("The cached vessel photo was unavailable")
        return None


def setup_dashboard(hass):
    """Register the send action and its private in-memory image store."""
    images = hass.data.setdefault(IMAGES, {})

    async def send_dashboard(call):
        if not hass.services.has_service("opendisplay", "upload_image"):
            raise HomeAssistantError("OpenDisplay image upload is unavailable")
        data = call.data
        rooms = [
            (
                room["name"],
                _value(hass.states.get(room["temperature"]), 1, "°C"),
                _value(hass.states.get(room["co2"]), 0, "ppm"),
            )
            for room in data["rooms"]
        ]
        weather = hass.states.get(data["weather"])
        vessel = hass.states.get(data["vessel"])
        attributes = vessel.attributes if vessel else {}
        condition = (
            weather.state
            if weather and weather.state not in {"unknown", "unavailable"}
            else "Unavailable"
        )
        condition = condition.replace("-", " ").capitalize()
        if condition == "Partlycloudy":
            condition = "Partly cloudy"
        name = (
            vessel.state
            if vessel and vessel.state not in {"unknown", "unavailable"}
            else "No vessel reported"
        )
        photo = await _photo(hass, attributes.get("picture_url"))
        image = await hass.async_add_executor_job(
            _render,
            rooms,
            _value(hass.states.get(data["outdoor_temperature"]), 1, "°C"),
            condition,
            name,
            photo,
            attributes.get("photo_author"),
        )
        identifier = uuid4().hex
        images[identifier] = image
        try:
            await hass.services.async_call(
                "opendisplay",
                "upload_image",
                {
                    "device_id": data["device_id"],
                    "image": {
                        "media_content_id": f"media-source://{DOMAIN}/{identifier}",
                        "media_content_type": "image/png",
                    },
                    "dither_mode": "none",
                },
                blocking=True,
                context=call.context,
            )
        finally:
            images.pop(identifier, None)

    hass.services.async_register(
        DOMAIN, "send_dashboard", send_dashboard, schema=SCHEMA
    )
