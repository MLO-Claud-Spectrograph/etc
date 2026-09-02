from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from astropy import constants as const, units as u
from shared_data import CSV_FILES, REFERENCE_SPECTRA
from simulator import (
    AtmosphericExtinction,
    DetectorModel,
    InstrumentSimulator,
    SpectrographModel,
    ThroughputCurve,
    f_lambda_to_photon_flux_density,
)
from simulator.core import FLUX_DENSITY_UNIT, TELESCOPE_AREA

TELESCOPE_FOCAL_LENGTH = 8125 * u.mm
DEFAULT_FIBER_LENGTH = 10 * u.m
DEFAULT_AIRMASS = 1.3

# Approximate Johnson B/V photon-counting response curves. Wavelengths are Angstroms.
PHOTOMETRIC_BANDPASSES: dict[str, np.ndarray] = {
    "g": np.array(
        [
            [3850, 0.000],
            [3900, 0.065],
            [3950, 0.223],
            [4000, 0.408],
            [4050, 0.594],
            [4100, 0.780],
            [4150, 0.914],
            [4200, 0.928],
            [5350, 0.928],
            [5400, 0.878],
            [5450, 0.718],
            [5500, 0.534],
            [5550, 0.350],
            [5600, 0.166],
            [5650, 0.037],
            [5700, 0.000],
        ],
        dtype=float,
    ),
    "r": np.array(
        [
            [5350, 0.000],
            [5400, 0.057],
            [5450, 0.207],
            [5500, 0.396],
            [5550, 0.585],
            [5600, 0.773],
            [5650, 0.919],
            [5700, 0.943],
            [6750, 0.943],
            [6800, 0.882],
            [6850, 0.698],
            [6900, 0.509],
            [6950, 0.321],
            [7000, 0.132],
            [7050, 0.019],
            [7100, 0.000],
        ],
        dtype=float,
    ),
    "i": np.array(
        [
            [6750, 0.000],
            [6800, 0.075],
            [6850, 0.243],
            [6900, 0.429],
            [6950, 0.616],
            [7000, 0.802],
            [7050, 0.928],
            [7100, 0.933],
            [8000, 0.933],
            [8050, 0.910],
            [8100, 0.765],
            [8150, 0.579],
            [8200, 0.392],
            [8250, 0.205],
            [8300, 0.056],
            [8350, 0.000],
        ],
        dtype=float,
    ),
}

AB_ZERO_POINT_JY = 3631.0


@dataclass(frozen=True)
class CameraConfig:
    qe_resource: str
    nx: int
    ny: int
    pixel_size: u.Quantity
    read_noise: u.Quantity


@dataclass
class SNRBinResult:
    wave_center_nm: float
    source_counts: float
    sky_counts: float
    snr: float
    component_averages: dict[str, float]


class ETCCalculator:
    CAMERA_CONFIGS = {
        "Kepler": CameraConfig(
            qe_resource="gsense400bsi_qe",
            nx=2048,
            ny=2048,
            pixel_size=11*u.um,
            read_noise=1.6*u.electron,
        ),
        "Moravian": CameraConfig(
            qe_resource="gsense4040bsi_qe",
            nx=4096,
            ny=4096,
            pixel_size=9*u.um,
            read_noise=3.9*u.electron,
        ),
        "QHY268": CameraConfig(
            qe_resource="qhy268_qe",
            nx=6280,
            ny=4210,
            pixel_size=3.76*u.um,
            read_noise=2.3*u.electron,
        ),
        "STF8300": CameraConfig(
            qe_resource="kaf8300c_qe",
            nx=3352,
            ny=2532,
            pixel_size=5.4*u.um,
            read_noise=9.3*u.electron,
        ),
    }

    THROUGHPUT_COMPONENTS = (
        "atmosphere",
        "fiber",
        "misc",
        "collimator",
        "grating",
        "window",
        "detector",
    )

    def __init__(self, fiber_length_m: float = DEFAULT_FIBER_LENGTH.to_value(u.m)):
        self.fiber_length = float(fiber_length_m) * u.m
        if self.fiber_length < 0 * u.m:
            raise ValueError("Fiber length cannot be negative.")

    @property
    def available_gratings(self) -> list[int | str]:
        return [1294, 1229, "thorlabs"]

    @property
    def available_camera_models(self) -> list[str]:
        return list(self.CAMERA_CONFIGS)

    @property
    def available_magnitude_bands(self) -> list[str]:
        return list(PHOTOMETRIC_BANDPASSES)

    def _camera_config(self, camera_model: str) -> CameraConfig:
        try:
            return self.CAMERA_CONFIGS[camera_model]
        except KeyError as exc:
            supported = ", ".join(self.available_camera_models)
            raise ValueError(f"Unsupported camera model '{camera_model}'. Supported: {supported}") from exc

    def detector_model(self, camera_model: str) -> DetectorModel:
        camera = self._camera_config(camera_model)
        return DetectorModel(
            nx=camera.nx,
            ny=camera.ny,
            pixel_size=camera.pixel_size,
            read_noise=camera.read_noise,
        )

    def spectrograph_model(self, camera_model: str) -> SpectrographModel:
        return SpectrographModel(
            detector=self.detector_model(camera_model),
            groove_density=300/u.mm,
            incidence_angle=32*u.deg,
            diffraction_angle=-20*u.deg,
            collimator_focal_length=180*u.mm,
            camera_focal_length=100*u.mm,
            fiber_core_diameter=105*u.um,
            diffraction_order=1,
        )

    def default_read_noise_for_camera(self, camera_model: str) -> float:
        return self._camera_config(camera_model).read_noise.to_value(u.electron)

    def dispersion_for_camera(self, camera_model: str) -> float:
        return abs(self.spectrograph_model(camera_model).dispersion.to_value(u.nm / u.pixel))

    def spatial_aperture_for_camera(self, camera_model: str) -> float:
        return self.spectrograph_model(camera_model).spatial_fwhm_px.to_value(u.pixel)

    @property
    def fiber_sky_area_arcsec2(self) -> float:
        spectrograph = self.spectrograph_model(self.available_camera_models[0])
        angular_diameter_rad = (
            spectrograph.fiber_core_diameter / TELESCOPE_FOCAL_LENGTH
        ).to_value(u.dimensionless_unscaled)
        angular_diameter_arcsec = angular_diameter_rad * u.rad.to(u.arcsec)
        return float(np.pi * (angular_diameter_arcsec / 2) ** 2)

    @staticmethod
    def _read_curve(resource_key: str) -> tuple[np.ndarray, np.ndarray]:
        values = np.loadtxt(CSV_FILES[resource_key], delimiter=",")
        wavelength = np.asarray(values[:, 0], dtype=float)
        throughput = np.asarray(values[:, 1], dtype=float)
        order = np.argsort(wavelength)
        wavelength = wavelength[order]
        throughput = throughput[order]
        if np.nanmax(throughput) > 1.5:
            throughput = throughput / 100.0
        return wavelength, throughput

    def _fiber_curve(self, fiber_length_m: float | None = None) -> ThroughputCurve:
        attenuation = np.loadtxt(CSV_FILES["fiber_attenuation"], delimiter=",")
        wavelength_nm, attenuation_db_per_km = attenuation.T
        length = self.fiber_length if fiber_length_m is None else float(fiber_length_m) * u.m
        if length < 0 * u.m:
            raise ValueError("Fiber length cannot be negative.")
        transmission = 10 ** (-attenuation_db_per_km * length.to_value(u.km) / 10)
        return ThroughputCurve(wavelength_nm * u.nm, transmission, name="fiber")

    def _grating_curve(self, grating_id: int | str) -> ThroughputCurve:
        if grating_id == 1294:
            return ThroughputCurve.from_csv(CSV_FILES["master 1294 unpolarized"], name="grating")
        if grating_id == "thorlabs":
            return ThroughputCurve.from_csv(CSV_FILES["gr50a-0305_efficiency-780"], name="grating")
        if grating_id != 1229:
            raise ValueError(f"Unsupported grating '{grating_id}'. Supported: 1229, 1294, 'thorlabs'")

        p_wave, p_efficiency = self._read_curve("master 1229 P plane")
        s_wave, s_efficiency = self._read_curve("master 1229 S plane")
        wave_min = min(p_wave.min(), s_wave.min())
        wave_max = max(p_wave.max(), s_wave.max())
        wavelength_nm = np.arange(np.floor(wave_min), np.ceil(wave_max) + 1)
        p_interp = np.interp(wavelength_nm, p_wave, p_efficiency, left=np.nan, right=np.nan)
        s_interp = np.interp(wavelength_nm, s_wave, s_efficiency, left=np.nan, right=np.nan)
        efficiency = np.nanmean(np.vstack((p_interp, s_interp)), axis=0)
        efficiency = np.nan_to_num(efficiency, nan=0.0)
        return ThroughputCurve(
            wavelength_nm * u.nm,
            efficiency,
            name="grating",
        )

    def throughput_curves(
        self,
        camera_model: str,
        grating_id: int | str,
        airmass: float = DEFAULT_AIRMASS,
        fiber_length_m: float | None = None,
    ) -> dict[str, ThroughputCurve]:
        if airmass <= 0:
            raise ValueError("Airmass must be positive.")
        camera = self._camera_config(camera_model)
        return {
            "atmosphere": AtmosphericExtinction(airmass=float(airmass)),
            "fiber": self._fiber_curve(fiber_length_m),
            "misc": ThroughputCurve(np.array([3000.0, 10500.0])*u.AA, np.array([0.95, 0.95]), name="misc"),
            "collimator": ThroughputCurve.from_csv(CSV_FILES["thorlabs_ar_coating"], name="collimator"),
            "grating": self._grating_curve(grating_id),
            "window": ThroughputCurve.from_csv(CSV_FILES["UVFS_coating"], name="window"),
            "detector": ThroughputCurve.from_csv(CSV_FILES[camera.qe_resource], name="detector"),
        }

    def get_throughput_components(
        self,
        wave_nm: np.ndarray,
        camera_model: str,
        grating_id: int | str,
        airmass: float = DEFAULT_AIRMASS,
        fiber_length_m: float | None = None,
        throughput_toggles: Mapping[str, bool] | None = None,
    ) -> dict[str, np.ndarray]:
        wavelength = np.asarray(wave_nm, dtype=float) * u.nm
        curves = self.throughput_curves(
            camera_model=camera_model,
            grating_id=grating_id,
            airmass=airmass,
            fiber_length_m=fiber_length_m,
        )
        toggles = {name: True for name in self.THROUGHPUT_COMPONENTS}
        if throughput_toggles:
            toggles.update(throughput_toggles)

        values = {name: curve(wavelength) for name, curve in curves.items()}
        active_curves = [curve for name, curve in curves.items() if toggles.get(name, True)]
        simulator = InstrumentSimulator(
            spectrograph=self.spectrograph_model(camera_model),
            throughputs=active_curves,
        )
        values["total"] = simulator.combined_throughput(wavelength)
        return values

    @staticmethod
    def get_dark_current(temp_c: float) -> float:
        plot_temps_dc = np.array([-20, -15, -10, -5, 0, 5, 10, 15, 20], dtype=float)
        dc_vals = np.array(
            [
                0.00053145,
                0.00062832,
                0.001309,
                0.0018326,
                0.0036652,
                0.0059756,
                0.010472,
                0.019111,
                0.036913,
            ],
            dtype=float,
        )
        return float(np.interp(temp_c, plot_temps_dc, dc_vals))

    @staticmethod
    def load_spectrum(spectrum_file: Path | str) -> np.ndarray:
        spec = np.genfromtxt(spectrum_file, dtype=[("wave", float), ("flux", float)])
        if spec.ndim == 0 or spec.size < 2:
            raise ValueError("Spectrum must contain at least two wavelength/flux rows.")
        spec = np.sort(spec, order="wave")
        spec["wave"] /= 10.0
        return spec

    def get_band_flux_density_jy(self, spectrum: np.ndarray, magnitude_band: str) -> float:
        if magnitude_band not in PHOTOMETRIC_BANDPASSES:
            supported = ", ".join(self.available_magnitude_bands)
            raise ValueError(f"Unsupported magnitude band '{magnitude_band}'. Supported: {supported}")

        wave_angstrom = u.Quantity(spectrum["wave"], unit=u.nm).to_value(u.AA)
        flux_lambda = np.asarray(spectrum["flux"], dtype=float)
        order = np.argsort(wave_angstrom)
        wave_angstrom = wave_angstrom[order]
        flux_lambda = flux_lambda[order]

        bandpass = PHOTOMETRIC_BANDPASSES[magnitude_band]
        supported_wave = bandpass[bandpass[:, 1] > 0, 0]
        finite_wave = wave_angstrom[np.isfinite(wave_angstrom)]
        if (
            finite_wave.size < 2
            or finite_wave.min() > supported_wave.min()
            or finite_wave.max() < supported_wave.max()
        ):
            raise ValueError(f"Spectrum does not fully cover the LSST {magnitude_band} band.")

        response = np.interp(
            wave_angstrom,
            bandpass[:, 0],
            bandpass[:, 1],
            left=0.0,
            right=0.0,
        )
        valid = (
            np.isfinite(wave_angstrom)
            & np.isfinite(flux_lambda)
            & (wave_angstrom > 0)
            & (response > 0)
        )
        if np.count_nonzero(valid) < 2:
            raise ValueError(f"Spectrum does not adequately sample the LSST {magnitude_band} band.")

        wave_valid = wave_angstrom[valid]
        response_valid = response[valid]
        flux_valid = flux_lambda[valid]
        denominator = np.trapezoid(response_valid / wave_valid, x=wave_valid)
        numerator = np.trapezoid(
            flux_valid * wave_valid * response_valid,
            x=wave_valid,
        )
        if denominator <= 0:
            raise ValueError(f"Could not integrate the LSST {magnitude_band} bandpass.")

        light_speed = const.c.to_value(u.AA / u.s)
        flux_nu_cgs = numerator / (light_speed * denominator)
        flux_nu_jy = float(flux_nu_cgs / 1e-23)
        if not np.isfinite(flux_nu_jy) or flux_nu_jy <= 0:
            raise ValueError(
                f"Spectrum has non-positive synthetic flux in the LSST {magnitude_band} band."
            )
        return flux_nu_jy

    def scale_spectrum_to_magnitude(
        self,
        spectrum: np.ndarray,
        target_magnitude: float,
        magnitude_band: str,
    ) -> tuple[np.ndarray, float]:
        current_flux_jy = self.get_band_flux_density_jy(spectrum, magnitude_band)
        target_flux_jy = AB_ZERO_POINT_JY * 10 ** (-0.4 * target_magnitude)
        scale_factor = float(target_flux_jy / current_flux_jy)
        scaled_spectrum = np.array(spectrum, copy=True)
        scaled_spectrum["flux"] *= scale_factor
        return scaled_spectrum, scale_factor

    @staticmethod
    def _sky_flux_density(wavelength: u.Quantity, sky_brightness: float) -> u.Quantity:
        flux_nu = (sky_brightness * u.ABmag).to(u.Jy)
        return flux_nu.to(
            FLUX_DENSITY_UNIT,
            equivalencies=u.spectral_density(wavelength),
        )

    @staticmethod
    def _integrated_electron_rate(
        wavelength: u.Quantity,
        flux_density: u.Quantity,
        throughput: np.ndarray,
    ) -> float:
        photon_flux_density = f_lambda_to_photon_flux_density(
            wavelength,
            flux_density,
            TELESCOPE_AREA,
        )
        wavelength_angstrom = wavelength.to_value(u.AA)
        detected_rate_density = (
            photon_flux_density * np.asarray(throughput, dtype=float)
        ).to_value(1 / u.s / u.AA)
        return float(np.trapezoid(detected_rate_density, x=wavelength_angstrom))

    def get_SNR_from_spectrum(
        self,
        exp_time: float,
        spectrum_file: Path | str,
        wave_centers: Iterable[float],
        binsize: float,
        sky_brightness: float = 21.6,
        camera_model: str = "QHY268",
        grating_id: int | str = 1229,
        airmass: float = DEFAULT_AIRMASS,
        fiber_length_m: float | None = None,
        temp: float = -10,
        target_magnitude: float | None = None,
        magnitude_band: str | None = None,
        throughput_toggles: Mapping[str, bool] | None = None,
        dispersion: float | None = None,
        spacial_aperture: float | None = None,
        read_noise_e: float | None = None,
    ) -> dict[str, object]:
        wave_centers = np.asarray(list(wave_centers), dtype=float)
        if wave_centers.size == 0:
            raise ValueError("At least one wavelength-bin center is required.")
        if exp_time <= 0:
            raise ValueError("Exposure time must be positive.")
        if binsize <= 0:
            raise ValueError("Bin size must be positive.")
        if np.any((wave_centers - binsize / 2) < 400) or np.any(
            (wave_centers + binsize / 2) > 900
        ):
            raise ValueError(
                "One or more bins extend outside the ETC wavelength range (400-900 nm)."
            )
        if temp < -20 or temp > 20:
            raise ValueError("Temperature must be between -20 and 20 C.")
        if airmass <= 0:
            raise ValueError("Airmass must be positive.")

        self._camera_config(camera_model)
        spec = self.load_spectrum(spectrum_file)
        spectrum_scale_factor = 1.0
        if target_magnitude is not None:
            if not magnitude_band:
                raise ValueError("A B or V magnitude band is required when scaling the spectrum.")
            spec, spectrum_scale_factor = self.scale_spectrum_to_magnitude(
                spec,
                target_magnitude=target_magnitude,
                magnitude_band=magnitude_band,
            )

        if dispersion is None:
            dispersion = self.dispersion_for_camera(camera_model)
        if spacial_aperture is None:
            spacial_aperture = self.spatial_aperture_for_camera(camera_model)
        if read_noise_e is None:
            read_noise_e = self.default_read_noise_for_camera(camera_model)
        if dispersion <= 0 or spacial_aperture <= 0 or read_noise_e < 0:
            raise ValueError("Detector extraction parameters must be non-negative and non-zero.")

        n_wave = binsize / dispersion
        n_total = n_wave * spacial_aperture
        read_noise_var = read_noise_e**2 * n_total
        dark_current = self.get_dark_current(temp)
        dark_counts = dark_current * n_total * exp_time
        fiber_sky_area = self.fiber_sky_area_arcsec2

        results: list[SNRBinResult] = []
        plot_wave = None
        plot_components = None

        for center in wave_centers:
            wave_min = center - binsize / 2
            wave_max = center + binsize / 2
            in_bin = (spec["wave"] >= wave_min) & (spec["wave"] <= wave_max)
            wave_bin_nm = np.asarray(spec["wave"][in_bin], dtype=float)
            if wave_bin_nm.size < 2:
                raise ValueError(f"No sufficient spectral samples in bin around {center} nm.")

            components = self.get_throughput_components(
                wave_bin_nm,
                camera_model=camera_model,
                grating_id=grating_id,
                airmass=airmass,
                fiber_length_m=fiber_length_m,
                throughput_toggles=throughput_toggles,
            )

            wavelength = wave_bin_nm * u.nm
            source_flux = np.asarray(spec["flux"][in_bin], dtype=float) * FLUX_DENSITY_UNIT
            source_rate = self._integrated_electron_rate(
                wavelength,
                source_flux,
                components["total"],
            )
            sky_rate_per_arcsec2 = self._integrated_electron_rate(
                wavelength,
                self._sky_flux_density(wavelength, sky_brightness),
                components["total"],
            )

            source_counts = source_rate * exp_time
            sky_counts = sky_rate_per_arcsec2 * fiber_sky_area * exp_time
            variance = source_counts + sky_counts + dark_counts + read_noise_var
            snr_bin = source_counts / np.sqrt(variance) if variance > 0 else 0.0

            results.append(
                SNRBinResult(
                    wave_center_nm=float(center),
                    source_counts=float(source_counts),
                    sky_counts=float(sky_counts),
                    snr=float(snr_bin),
                    component_averages={
                        name: float(np.mean(values))
                        for name, values in components.items()
                    },
                )
            )

            if plot_wave is None:
                plot_wave = wave_bin_nm
                plot_components = components

        return {
            "bins": results,
            "meta": {
                "exp_time": float(exp_time),
                "n_total_pixels": float(n_total),
                "n_wave_pixels": float(n_wave),
                "spatial_aperture_pix": float(spacial_aperture),
                "dispersion_nm_per_pix": float(dispersion),
                "read_noise_var": float(read_noise_var),
                "dark_counts": float(dark_counts),
                "dark_current": float(dark_current),
                "fiber_sky_area_arcsec2": float(fiber_sky_area),
                "camera_model": camera_model,
                "read_noise_e": float(read_noise_e),
                "grating": grating_id,
                "airmass": float(airmass),
                "spectrum_scale_factor": float(spectrum_scale_factor),
                "target_magnitude": target_magnitude,
                "magnitude_band": magnitude_band,
            },
            "throughput_plot": {
                "wave_nm": plot_wave,
                "components": plot_components,
            },
        }


def get_default_spectrum_file():
    return REFERENCE_SPECTRA["SNIa_max_z0p05"]
