from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import numpy as np

try:
    from specreduce.calibration_data import AtmosphericExtinction, SUPPORTED_EXTINCTION_MODELS
except Exception:  # pragma: no cover - optional dependency fallback
    AtmosphericExtinction = None
    SUPPORTED_EXTINCTION_MODELS = []

PLANCK_H = 6.62607015e-34
LIGHT_C = 2.99792458e8


@dataclass
class SNRBinResult:
    wave_center_nm: float
    source_counts: float
    sky_counts: float
    snr: float
    component_averages: Dict[str, float]


class ETCCalculator:
    CAMERA_QE_FILES: Dict[str, str] = {
        "QHY268": "qhy268_qe.csv",
        "Kepler": "Kepler_qe.csv",
        "Moravian": "Moravian_qe.csv",
    }
    CAMERA_READ_NOISE_DEFAULTS: Dict[str, float] = {
        "QHY268": 2.3,
        "Kepler": 1.6,
        "Moravian": 3.9,
    }

    def __init__(self, data_root: Optional[Path] = None, fiber_length_m: Optional[float] = 10.0):
        self.data_root = Path(data_root) if data_root else Path(__file__).resolve().parents[1] / "data"
        self.csv_root = self.data_root / "csv files"
        self.fiber_length_m = fiber_length_m
        self._load_curves()

    @staticmethod
    def _interp_with_linear_extrapolation(x: np.ndarray, xp: np.ndarray, fp: np.ndarray) -> np.ndarray:
        values = np.interp(x, xp, fp)
        if xp.size < 2:
            return values

        fit_points = min(5, xp.size)
        left_slope, left_intercept = np.polyfit(xp[:fit_points], fp[:fit_points], 1)
        right_slope, right_intercept = np.polyfit(xp[-fit_points:], fp[-fit_points:], 1)

        left_mask = x < xp[0]
        right_mask = x > xp[-1]
        if np.any(left_mask):
            values[left_mask] = left_slope * x[left_mask] + left_intercept
        if np.any(right_mask):
            values[right_mask] = right_slope * x[right_mask] + right_intercept
        return values

    def _load_curves(self) -> None:
        dtype = [("wave", float), ("tp", float)]

        self.camera_qe_curves: Dict[str, np.ndarray] = {}
        for camera_model, filename in self.CAMERA_QE_FILES.items():
            curve = np.sort(
                np.genfromtxt(self.csv_root / filename, dtype=dtype, delimiter=",")
            )
            # Some QE files are stored as percentages (0-100) while others are fractions (0-1).
            if np.nanmax(curve["tp"]) > 1.5:
                curve["tp"] = curve["tp"] / 100.0
            self.camera_qe_curves[camera_model] = curve
        self.grat_1294 = np.sort(np.genfromtxt(self.csv_root / "master 1294 unpolarized.csv", dtype=dtype, delimiter=","))
        self.grat_1229_p = np.sort(np.genfromtxt(self.csv_root / "master 1229 P plane.csv", dtype=dtype, delimiter=","))
        self.grat_1229_s = np.sort(np.genfromtxt(self.csv_root / "master 1229 S plane.csv", dtype=dtype, delimiter=","))
        self.fiber_att = np.sort(np.genfromtxt(self.csv_root / "fiber_attenuation.csv", dtype=dtype, delimiter=","))

        self.fiber_att["tp"] = 10 ** (-(self.fiber_att["tp"] * (self.fiber_length_m/1000.0)) / 10)

        self.std_wave_grid = np.arange(314.0, 901.0)
        p_interp = self._interp_with_linear_extrapolation(self.std_wave_grid, self.grat_1229_p["wave"], self.grat_1229_p["tp"])
        s_interp = self._interp_with_linear_extrapolation(self.std_wave_grid, self.grat_1229_s["wave"], self.grat_1229_s["tp"])
        self.mean_1229 = np.nanmean([p_interp, s_interp], axis=0)

        self.airmass_models: Dict[str, np.ndarray] = {}
        if AtmosphericExtinction is not None and SUPPORTED_EXTINCTION_MODELS:
            interp_models = []
            for model in SUPPORTED_EXTINCTION_MODELS:
                ext = AtmosphericExtinction(model=model)
                wave_nm = np.asarray(ext.spectral_axis) / 10.0
                transmission = np.asarray(ext.transmission)
                curve = np.interp(self.std_wave_grid, wave_nm, transmission)
                self.airmass_models[model] = curve
                interp_models.append(curve)
            self.airmass_models["average"] = np.nanmean(interp_models, axis=0)
        else:
            self.airmass_models["average"] = np.ones_like(self.std_wave_grid)

    @property
    def available_gratings(self) -> List[int]:
        return [1229, 1294]

    @property
    def available_airmass_models(self) -> List[str]:
        return sorted(self.airmass_models.keys(), key=lambda m: (m != "average", m))

    @property
    def available_camera_models(self) -> List[str]:
        return list(self.CAMERA_QE_FILES.keys())

    def _validate_camera_model(self, camera_model: str) -> None:
        if camera_model not in self.CAMERA_QE_FILES:
            raise ValueError(
                f"Unsupported camera model '{camera_model}'. Supported: {', '.join(self.available_camera_models)}"
            )

    def default_read_noise_for_camera(self, camera_model: str) -> float:
        self._validate_camera_model(camera_model)
        return self.CAMERA_READ_NOISE_DEFAULTS[camera_model]

    def _interp_scalar(self, wave_nm: float, wave_grid: np.ndarray, values: np.ndarray) -> float:
        return float(np.interp(wave_nm, wave_grid, values))

    def get_qe(self, wave_nm: float, camera_model: str = "QHY268") -> float:
        self._validate_camera_model(camera_model)
        curve = self.camera_qe_curves[camera_model]
        return self._interp_scalar(wave_nm, curve["wave"], curve["tp"])

    def get_gr(self, wave_nm: float, grat_master_num: int) -> float:
        if grat_master_num == 1229:
            return float(self._interp_with_linear_extrapolation(np.asarray([wave_nm], dtype=float), self.std_wave_grid, self.mean_1229)[0])
        if grat_master_num == 1294:
            return float(self._interp_with_linear_extrapolation(np.asarray([wave_nm], dtype=float), self.grat_1294["wave"], self.grat_1294["tp"])[0])
        raise ValueError(f"Unsupported grating '{grat_master_num}'. Supported: 1229, 1294")

    def get_fib_att(self, wave_nm: float) -> float:
        return self._interp_scalar(wave_nm, self.fiber_att["wave"], self.fiber_att["tp"])

    def get_airmass_ext(self, wave_nm: float, model: str) -> float:
        if model not in self.airmass_models:
            raise ValueError(
                f"Unsupported airmass model '{model}'. Supported: {', '.join(self.available_airmass_models)}"
            )
        return self._interp_scalar(wave_nm, self.std_wave_grid, self.airmass_models[model])

    def get_dark_current(self, temp_c: float) -> float:
        plot_temps_dc = np.array([-20, -15, -10, -5, 0, 5, 10, 15, 20], dtype=float)
        dc_vals = np.array([0.00053145, 0.00062832, 0.001309, 0.0018326, 0.0036652, 0.0059756, 0.010472, 0.019111, 0.036913], dtype=float)
        return float(np.interp(temp_c, plot_temps_dc, dc_vals))

    def load_spectrum(self, spectrum_file: Path | str, z: float) -> np.ndarray:
        spec = np.genfromtxt(spectrum_file, dtype=[("wave", float), ("flux", float)])
        spec["wave"] *= 1.0 / (1.0 + z)
        spec["wave"] /= 10.0
        return spec

    def get_throughput_components(
        self,
        wave_nm: np.ndarray,
        camera_model: str,
        grat_master_num: int,
        airmass_model: str,
        lens: float,
        throughput_toggles: Optional[Dict[str, bool]] = None,
    ) -> Dict[str, np.ndarray]:
        toggles = {
            "detector": True,
            "grating": True,
            "fiber": True,
            "airmass": True,
            "lens": True,
        }
        if throughput_toggles:
            toggles.update(throughput_toggles)

        detector = np.array([self.get_qe(w, camera_model=camera_model) for w in wave_nm])
        grating = np.array([max(self.get_gr(w, grat_master_num) - 0.1, 0.0) for w in wave_nm])
        fiber = np.array([self.get_fib_att(w) for w in wave_nm])
        airmass = np.array([self.get_airmass_ext(w, airmass_model) for w in wave_nm])
        lens_arr = np.full_like(wave_nm, fill_value=lens, dtype=float)

        total = np.ones_like(wave_nm, dtype=float)
        for name, arr in {
            "detector": detector,
            "grating": grating,
            "fiber": fiber,
            "airmass": airmass,
            "lens": lens_arr,
        }.items():
            if toggles.get(name, True):
                total *= arr

        return {
            "detector": detector,
            "grating": grating,
            "fiber": fiber,
            "airmass": airmass,
            "lens": lens_arr,
            "total": total,
        }

    def get_flux_density_w_m2_nm(self, wavelength_nm: float, mag_ab: float) -> float:
        wavelength_m = wavelength_nm * 1e-9
        f_nu = 3631e-26 * (10 ** (-mag_ab / 2.5))
        return float(f_nu * LIGHT_C / (wavelength_m**2) * 1e-9)

    def get_SNR_from_spectrum(
        self,
        exp_time: float,
        spectrum_file: Path | str,
        z: float,
        wave_centers: Iterable[float],
        binsize: float,
        dispersion: float = 0.14,
        spacial_aperture: float = 13,
        sky_brightness: float = 21.6,
        read_noise_e: Optional[float] = None,
        pix_scale: float = 0.8,
        camera_model: str = "QHY268",
        grat_master_num: int = 1229,
        airmass_model: str = "average",
        lens: float = 0.99,
        t_diam: float = 1250,
        temp: float = -10,
        throughput_toggles: Optional[Dict[str, bool]] = None,
    ) -> Dict[str, object]:
        wave_centers = np.array(list(wave_centers), dtype=float)

        if np.any((wave_centers - binsize / 2) < 400) or np.any((wave_centers + binsize / 2) > 900):
            raise ValueError(
                f"One or more bin centers ({wave_centers}) are outside instrument range ({400+binsize}-{900-binsize} nm) for binsize={binsize}."
            )
        if not binsize > 0:
            raise ValueError("Bin size must be positive.")
        if temp < -20 or temp > 20:
            raise ValueError("Temperature must be between -20 and 20 C.")
        self._validate_camera_model(camera_model)

        spec = self.load_spectrum(spectrum_file, z)
        n_wave = binsize / dispersion
        n_spacial = spacial_aperture
        n_total = n_wave * n_spacial
        if read_noise_e is None:
            read_noise_e = self.default_read_noise_for_camera(camera_model)
        read_noise_var = read_noise_e**2 * n_total
        dark_current = self.get_dark_current(temp)
        dark_counts = dark_current * n_total * exp_time

        t_area = np.pi * (t_diam * 1e-3 / 2.0) ** 2

        results: List[SNRBinResult] = []
        plot_wave = None
        plot_components = None

        for center in wave_centers:
            wave_min = center - binsize / 2.0
            wave_max = center + binsize / 2.0
            w = (spec["wave"] >= wave_min) & (spec["wave"] <= wave_max)
            wave_bin = np.array(spec["wave"][w], dtype=float)
            if wave_bin.size < 2:
                raise ValueError(f"No sufficient spectral samples in bin around {center} nm.")

            components = self.get_throughput_components(
                wave_bin,
                camera_model=camera_model,
                grat_master_num=grat_master_num,
                airmass_model=airmass_model,
                lens=lens,
                throughput_toggles=throughput_toggles,
            )

            flux_erg_cm2_a = np.array(spec["flux"][w], dtype=float)
            flux_w_m2_nm = flux_erg_cm2_a * 1e-2

            wave_m = wave_bin * 1e-9
            s_obs_spec = flux_w_m2_nm * wave_m / (PLANCK_H * LIGHT_C) * t_area * components["total"]
            s_ob_bin = float(np.trapezoid(s_obs_spec, x=wave_bin))

            sky_flux = np.array([self.get_flux_density_w_m2_nm(w, sky_brightness) for w in wave_bin], dtype=float)
            s_sky_spec = sky_flux * wave_m / (PLANCK_H * LIGHT_C) * t_area * components["total"]
            s_sky_bin = float(np.trapezoid(s_sky_spec, x=wave_bin))

            source_counts = s_ob_bin * exp_time
            extraction_area = n_total * pix_scale**2
            sky_counts = s_sky_bin * exp_time * extraction_area

            denom = np.sqrt(source_counts + sky_counts + dark_counts + read_noise_var)
            snr_bin = float(source_counts / denom) if denom > 0 else 0.0

            component_averages = {k: float(np.mean(v)) for k, v in components.items()}
            results.append(
                SNRBinResult(
                    wave_center_nm=float(center),
                    source_counts=float(source_counts),
                    sky_counts=float(sky_counts),
                    snr=snr_bin,
                    component_averages=component_averages,
                )
            )

            if plot_wave is None:
                plot_wave = wave_bin
                plot_components = components

        return {
            "bins": results,
            "meta": {
                "exp_time": exp_time,
                "n_total_pixels": n_total,
                "read_noise_var": read_noise_var,
                "dark_counts": dark_counts,
                "dark_current": dark_current,
                "camera_model": camera_model,
                "read_noise_e": read_noise_e,
                "grating": grat_master_num,
                "airmass_model": airmass_model,
            },
            "throughput_plot": {
                "wave_nm": plot_wave,
                "components": plot_components,
            },
        }


def get_default_spectrum_file() -> Path:
    return Path(__file__).resolve().parents[1] / "data" / "SN_ref_spectra" / "SNIa_max_z0p05.txt"


if __name__ == "__main__":
    calc = ETCCalculator()
    result = calc.get_SNR_from_spectrum(
        exp_time=7200,
        spectrum_file=get_default_spectrum_file(),
        z=0.05,
        wave_centers=[600, 700],
        binsize=5,
        grat_master_num=1294,
    )
    for row in result["bins"]:
        print(f"{row.wave_center_nm:.1f} nm -> SNR={row.snr:.3f}")
