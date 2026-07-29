"""How the phone was mounted on the car.

A phone bolted to the car in a different orientation measures the same drive
with permuted axes and flipped signs. Which sensor axis points forward cannot
be recovered from the recording afterwards - the sign of the longitudinal
acceleration is the same whether the phone is turned around or the car is
driving backwards. It therefore has to be documented, not inferred.

The catalogue below is that documentation. Students pick one key in
``metadata.json``; everything else - which column is the main axis, and with
which sign - follows from it.

Vehicle frame: ISO 8855, x forward, y left, z up, right-handed. Rotation rates
follow the right-hand rule about those axes, so a positive yaw rate is a left
turn.

Phone frame: the phyphox convention, x along the right edge of the screen,
y along the top edge, z out of the screen towards the viewer.
"""

VEHICLE_FRAME = "ISO 8855 (x forward, y left, z up)"

# Every entry gives, for each vehicle direction, the phone axis that points
# that way and its sign. All six are proper rotations, so the same table also
# maps the rotation rates: roll is about forward, pitch about left, yaw about up.
PHONE_MOUNTINGS = {
    "flat_screen_up_top_left": {
        "label": "flat, screen up, top edge to the left",
        "description": (
            "Phone lies flat on the car with the screen facing up and the top edge "
            "pointing to the vehicle's left side."
        ),
        "documented": True,
        "axes": {"main": ("x", 1), "lateral": ("y", 1), "vertical": ("z", 1)},
    },
    "flat_screen_up_top_forward": {
        "label": "flat, screen up, top edge forward",
        "description": (
            "Phone lies flat on the car with the screen facing up and the top edge "
            "pointing in the driving direction."
        ),
        "documented": True,
        "axes": {"main": ("y", 1), "lateral": ("x", -1), "vertical": ("z", 1)},
    },
    "flat_screen_up_top_right": {
        "label": "flat, screen up, top edge to the right",
        "description": (
            "Phone lies flat on the car with the screen facing up and the top edge "
            "pointing to the vehicle's right side."
        ),
        "documented": True,
        "axes": {"main": ("x", -1), "lateral": ("y", -1), "vertical": ("z", 1)},
    },
    "flat_screen_up_top_backward": {
        "label": "flat, screen up, top edge backward",
        "description": (
            "Phone lies flat on the car with the screen facing up and the top edge "
            "pointing against the driving direction."
        ),
        "documented": True,
        "axes": {"main": ("y", -1), "lateral": ("x", 1), "vertical": ("z", 1)},
    },
    "flat_screen_down_top_forward": {
        "label": "flat, screen down, top edge forward",
        "description": (
            "Phone lies flat on the car with the screen facing down towards the car "
            "and the top edge pointing in the driving direction."
        ),
        "documented": True,
        "axes": {"main": ("y", 1), "lateral": ("x", 1), "vertical": ("z", -1)},
    },
    "upright_screen_left_top_up": {
        "label": "upright, screen to the left, top edge up",
        "description": (
            "Phone stands upright on its long edge, screen facing the vehicle's left "
            "side, top edge pointing up."
        ),
        "documented": True,
        "axes": {"main": ("x", -1), "lateral": ("z", 1), "vertical": ("y", 1)},
    },
    "undocumented": {
        "label": "not documented",
        "description": (
            "The mounting was not recorded. The sensor axes are used as they are, "
            "which may mirror the driving direction and swap left and right turns."
        ),
        "documented": False,
        "axes": {"main": ("x", 1), "lateral": ("y", 1), "vertical": ("z", 1)},
    },
}

DEFAULT_PHONE_MOUNTING = "undocumented"

# Which config entry each vehicle direction fills, per analysis mode. The value
# is a prefix: "<prefix>_column" and "<prefix>_sign" in the analysis config,
# "<prefix>_value" and "<prefix>_smoothed" as working columns in the data frame.
AXIS_ROLES_BY_ANALYSIS = {
    "suspension_acceleration": {
        "main": "main_axis",
        "lateral": "lateral_axis",
        "vertical": "vertical_axis",
    },
    "suspension_angular_velocity": {
        "main": "roll_rate",
        "lateral": "pitch_rate",
        "vertical": "yaw_rate",
    },
}

ROLE_MEANING = {
    "suspension_acceleration": {
        "main": "acceleration forward",
        "lateral": "acceleration to the left",
        "vertical": "acceleration upward",
    },
    "suspension_angular_velocity": {
        "main": "roll rate, about the forward axis",
        "lateral": "pitch rate, about the left axis",
        "vertical": "yaw rate, about the up axis",
    },
}


def resolve_phone_mounting(metadata):
    """Return the catalogue entry named by ``suspension.phone_mounting``."""
    key = (metadata or {}).get("suspension", {}).get("phone_mounting") or DEFAULT_PHONE_MOUNTING
    if key not in PHONE_MOUNTINGS:
        raise ValueError(
            f"Unknown phone_mounting {key!r}. Valid values are: {', '.join(sorted(PHONE_MOUNTINGS))}. "
            "Set it in metadata.json under 'suspension'."
        )
    entry = dict(PHONE_MOUNTINGS[key])
    entry["key"] = key
    return entry


def axis_letter_and_sign(mounting, role):
    """Return the phone axis letter and sign for a vehicle direction."""
    return mounting["axes"][role]


def mounting_is_documented(mounting):
    return bool(mounting.get("documented"))


def describe_phone_mounting(mounting, analysis_key=None):
    """Return display rows describing the mounting and the resulting axis roles."""
    rows = [
        {"item": "phone_mounting", "value": mounting["key"], "meaning": mounting["label"]},
        {"item": "vehicle_frame", "value": VEHICLE_FRAME, "meaning": "reference the catalogue is defined against"},
    ]
    roles = AXIS_ROLES_BY_ANALYSIS.get(analysis_key, {})
    meanings = ROLE_MEANING.get(analysis_key, {})
    for role, prefix in roles.items():
        letter, sign = axis_letter_and_sign(mounting, role)
        rows.append(
            {
                "item": prefix,
                "value": f"{'+' if sign > 0 else '-'}{letter}",
                "meaning": meanings.get(role, role),
            }
        )
    return rows


def phone_mounting_table():
    """Catalogue overview for the metadata notebook."""
    import pandas as pd

    rows = []
    for key, entry in PHONE_MOUNTINGS.items():
        axes = entry["axes"]
        rows.append(
            {
                "phone_mounting": key,
                "mounting": entry["label"],
                "forward": _signed(axes["main"]),
                "left": _signed(axes["lateral"]),
                "up": _signed(axes["vertical"]),
            }
        )
    return pd.DataFrame(rows)


def _signed(axis):
    letter, sign = axis
    return f"{'+' if sign > 0 else '-'}{letter}"
