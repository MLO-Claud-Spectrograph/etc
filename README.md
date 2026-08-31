# Exposure Time Calculator (ETC)

Computes signal-to-noise ratio (SNR) in one or more wavelength bins for an input spectrum and exposure time.

The application reuses the instrument models in `spectrograph-sim` and the curves in `shared-data`, so the ETC and detector simulator use the same telescope area, atmospheric extinction, detector geometry, grating/optics throughput representation, and photon-flux conversion.

## Installation and launch

Install the package and its dependencies, then launch the GUI with:

```bash
pip install .
spectrograph-etc
```

The package is imported as `etc`.

## Spectrum input

Choose a two-column text spectrum containing:

1. wavelength in Angstrom
2. flux density in erg s^-1 cm^-2 Angstrom^-1

The packaged `SNIa_max_z0p05` spectrum from `shared-data` is offered as the initial reference location.

The optional **Flux scale magnitude** field rescales the entire input spectrum so that its synthetic Johnson B- or V-band AB magnitude matches the requested value. Leave the field blank to preserve the input spectrum's original flux normalization.

## Instrument options

- **Grating:** Newport 1229, Newport 1294, or the ThorLabs grating curve.
- **Airmass:** numerical airmass applied to the Palomar atmospheric-extinction curve from `spectrograph-sim`.
- **Camera model:** selects the detector QE, pixel size, detector dimensions, and read noise.

The throughput toggles expose the same component model used by the simulator: atmosphere, fiber, miscellaneous losses, collimator, grating, detector window, and detector QE.

Detector sampling parameters are not user inputs. Dispersion and projected fiber width are calculated from `SpectrographModel`, and read noise is taken from the selected camera configuration.

## SNR inputs

- **Exposure Time** (s)
- **Redshift**
- **Wave Centers** (nm), comma-separated
- **Bin Size** (nm)
- **Sky Brightness** (AB mag arcsec^-2; default 21.6)
- **Fiber Length** (m; default 10)
- **Temperature** (deg C; default -10)

The telescope diameter, pixel scale, lens throughput, detector read noise, dispersion, and spatial extraction width are no longer independent GUI inputs. Instrument geometry and throughput are taken from the shared simulator model instead.

Sky background is integrated over the fiber's on-sky aperture rather than multiplying a detector extraction pixel count by an independent pixel scale.

## Python API

```python
from etc import ETCCalculator, get_default_spectrum_file

calc = ETCCalculator()
result = calc.get_SNR_from_spectrum(
    exp_time=1800,
    spectrum_file=get_default_spectrum_file(),
    z=0.05,
    wave_centers=[550, 650, 750],
    binsize=5,
    camera_model="QHY268",
    grating_id=1294,
    airmass=1.3,
    target_magnitude=18.0,
    magnitude_band="V",
)
```
