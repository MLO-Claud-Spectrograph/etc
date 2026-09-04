from pathlib import Path

import numpy as np
from astropy import units as u

from etc.core import AB_ZERO_POINT_JY, ETCCalculator
from simulator.core import FLUX_DENSITY_UNIT


def _write_flat_spectrum(path: Path, f_nu_jy: float = AB_ZERO_POINT_JY) -> Path:
    wavelength = np.linspace(3500.0, 9500.0, 3001) * u.AA
    flux_nu = f_nu_jy * u.Jy
    flux_lambda = flux_nu.to(
        FLUX_DENSITY_UNIT,
        equivalencies=u.spectral_density(wavelength),
    )
    np.savetxt(path, np.column_stack((wavelength.value, flux_lambda.value)))
    return path


def test_detector_sampling_is_derived_from_camera():
    calc = ETCCalculator()
    qhy_dispersion = calc.dispersion_for_camera("QHY268")
    kepler_dispersion = calc.dispersion_for_camera("Kepler")
    assert qhy_dispersion > 0
    assert kepler_dispersion > qhy_dispersion
    spectrograph = calc.spectrograph_model("QHY268")
    extraction_aperture = calc.extraction_aperture_for_camera("QHY268")
    assert np.isclose(
        extraction_aperture,
        spectrograph.fiber_pitch_px.to_value(u.pixel),
    )
    assert extraction_aperture > spectrograph.spatial_fwhm_px.to_value(u.pixel)
    assert 0 < calc.extraction_fraction_for_camera("QHY268") <= 1


def test_load_spectrum_preserves_observed_wavelengths(tmp_path):
    spectrum_file = _write_flat_spectrum(tmp_path / "flat.txt")
    spectrum = ETCCalculator.load_spectrum(spectrum_file)
    assert np.isclose(spectrum["wave"][0], 350.0)
    assert np.isclose(spectrum["wave"][-1], 950.0)


def test_ab_magnitude_scaling(tmp_path):
    calc = ETCCalculator()
    spectrum_file = _write_flat_spectrum(tmp_path / "flat.txt")
    spectrum = calc.load_spectrum(spectrum_file)
    scaled, scale_factor = calc.scale_spectrum_to_magnitude(
        spectrum,
        target_magnitude=20.0,
        magnitude_band="r",
    )
    expected_jy = AB_ZERO_POINT_JY * 10 ** (-0.4 * 20.0)
    measured_jy = calc.get_band_flux_density_jy(scaled, "r")
    assert np.isclose(measured_jy, expected_jy, rtol=2e-3)
    assert scale_factor > 0


def test_total_throughput_uses_simulator_combination():
    calc = ETCCalculator()
    wavelength_nm = np.array([500.0, 600.0, 700.0])
    components = calc.get_throughput_components(
        wavelength_nm,
        camera_model="Kepler",
        grating_id=1294,
        airmass=1.3,
    )
    expected = np.ones_like(wavelength_nm)
    for name in calc.THROUGHPUT_COMPONENTS:
        expected *= components[name]
    assert np.allclose(components["total"], expected)


def test_line_resolved_sky_spectrum_is_available():
    calc = ETCCalculator()
    wavelength, flux_density = calc.sky_spectrum
    assert wavelength.size == flux_density.size
    assert wavelength.size > 10_000
    assert wavelength.min() < 400 * u.nm
    assert wavelength.max() > 900 * u.nm
    assert np.nanmax(flux_density.value) > 10 * np.nanmedian(flux_density.value)


def test_snr_smoke(tmp_path):
    calc = ETCCalculator()
    spectrum_file = _write_flat_spectrum(tmp_path / "flat.txt", f_nu_jy=1e-4)
    result = calc.get_SNR_from_spectrum(
        exp_time=60.0,
        spectrum_file=spectrum_file,
        wave_centers=[600.0],
        binsize=5.0,
        camera_model="Kepler",
        grating_id=1294,
        airmass=1.3,
    )
    row = result["bins"][0]
    assert np.isfinite(row.snr)
    assert row.snr > 0
    assert result["meta"]["dispersion_nm_per_pix"] > 0
    assert result["meta"]["fiber_sky_area_arcsec2"] > 0
    assert result["meta"]["detector_temperature_c"] == -20.0


def test_fiber_coupling_and_airmass_only_change_source(tmp_path):
    calc = ETCCalculator()
    spectrum_file = _write_flat_spectrum(tmp_path / "flat.txt", f_nu_jy=1e-4)
    common = {
        "exp_time": 60.0,
        "spectrum_file": spectrum_file,
        "wave_centers": [600.0],
        "binsize": 5.0,
        "camera_model": "Kepler",
        "grating_id": 1294,
        "airmass": 1.3,
    }
    full = calc.get_SNR_from_spectrum(**common, fiber_coupling_efficiency=100.0)
    half = calc.get_SNR_from_spectrum(**common, fiber_coupling_efficiency=50.0)
    high_airmass = calc.get_SNR_from_spectrum(
        **(common | {"airmass": 2.0}),
        fiber_coupling_efficiency=100.0,
    )
    full_bin = full["bins"][0]
    half_bin = half["bins"][0]
    high_airmass_bin = high_airmass["bins"][0]
    assert np.isclose(half_bin.source_counts, 0.5 * full_bin.source_counts)
    assert np.isclose(half_bin.sky_counts, full_bin.sky_counts)
    assert high_airmass_bin.source_counts < full_bin.source_counts
    assert np.isclose(high_airmass_bin.sky_counts, full_bin.sky_counts)
