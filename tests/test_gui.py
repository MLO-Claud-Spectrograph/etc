from etc.gui import ETCGui


class _Entry:
    def __init__(self, value: str, placeholder: str = ""):
        self._value = value
        self.placeholder = placeholder

    def value(self) -> str:
        return self._value


class _Variable:
    def __init__(self, value):
        self._value = value

    def get(self):
        return self._value


def test_optional_flux_scale_placeholder_is_not_parsed_as_float():
    gui = object.__new__(ETCGui)
    gui.entries = {
        "exp_time": _Entry("60"),
        "z": _Entry("0.05"),
        "wave_centers_nm": _Entry("600, 700"),
        "binsize_nm": _Entry("5"),
        "sky_brightness": _Entry("21.6"),
        "fiber_length_m": _Entry("10"),
        "temp_c": _Entry("-10"),
    }
    gui.magnitude_entry = _Entry("optional", placeholder="optional")
    gui.spectrum_path = _Variable("spectrum.txt")
    gui.camera_model = _Variable("QHY268")
    gui.grating = _Variable("1229")
    gui.airmass = _Variable("1.3")
    gui.magnitude_band = _Variable("g")
    gui.toggle_vars = {}

    params = ETCGui._read_inputs(gui)

    assert params["target_magnitude"] is None
