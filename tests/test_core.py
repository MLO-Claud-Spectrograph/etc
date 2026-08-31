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
    assert calc.spatial_aperture_for_camera("QHY268") > 0


def test_ab_magnitude_scaling(tmp_path):
    calc = ETCCalculator()
    spectrum_file = _write_flat_spectrum(tmp_path / "flat.txt")
    spectrum = calc.load_spectrum(spectrum_file, z=0.0)
    scaled, scale_factor = calc.scale_spectrum_to_magnitude(
        spectrum,
        target_magnitude=20.0,
        magnitude_band="V",
        magnitude_system="AB",
    )
    expected_jy = AB_ZERO_POINT_JY * 10 ** (-0.4 * 20.0)
    measured_jy = calc.get_band_flux_density_jy(scaled, "V")
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


def test_snr_smoke(tmp_path):
    calc = ETCCalculator()
    spectrum_file = _write_flat_spectrum(tmp_path / "flat.txt", f_nu_jy=1e-4)
    result = calc.get_SNR_from_spectrum(
        exp_time=60.0,
        spectrum_file=spectrum_file,
        z=0.0,
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
