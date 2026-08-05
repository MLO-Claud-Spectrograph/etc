# Exposure Time Calculator (ETC)

Outputs the Signal to Noise Ratio (SNR) at a given exposure time and wavelength bin(s) for an expected spectrum. To use the ETC, navigate to this directory and run `python3 ETC.py`. You should see 2 dialog boxes pop up. The following steps will guide you through the UI and features of the ETC.

#### 1. Select spectrum file:
In the small dialog box, click your desired spectrum file and then 'Open' to dismiss the box. The spectrum `SNIa_max_z0p05.txt` is the default spectrum, but any spectrum may be uploaded to the ETC, provided it is a `.txt` file and in a 2-column format. Wavelength should be in units of Angstrom and Flux should be in erg/s/cm2/A (or an equivalent quantity). Examine the default spectrum file for correct formatting.

#### 2. Choose instrument parameters:
There are 2 grating options and 8 airmass options to choose from the respective dropdown menus which help determine the overall instrument throughput:
- Gratings: Master numbers [1229](https://www.newport.com/mam/celum/celum_assets/np/270r_1299_m1_sp_200w.jpg) & [1294](https://www.newport.com/mam/celum/celum_assets/np/270r_1294_m1_unp_800w.jpg) from Newport. Grating 1229's throughput curve has been inferrred from an average of the S and P polarization angles.
- Airmass: There are 7 observatory airmass models as well as an average model to choose from. The 7 observatory models were taken from the `specreduce.calibration_data` package ([further details here](https://specreduce.readthedocs.io/en/stable/extinction.html)). The `Average` option is the average of all 7 observatory airmass curves.

When calculating throughput, the `Included Throughput Factors` box allows you to choose which instrument factors contribute to the total instrument throughput. The fiber and detector curves represent the individual components' throughput, like the grating/airmass curves. The lens curve is simply a constant factor of 0.99.

#### 3. Enter SNR inputs:
- `Exposure Time` (s): The desired time to generate SNR for.
- `Redshift`: The redshift of the host galaxy where the supernova/spectrum was observed (for the default spectrum, z = 0.05).
- `Wave Centers` (nm): A comma-seperated list of wave centers to evaluate SNR at.
- `Bin Size`: Size of the wavelength bins centered on each wave center
- `Dispersion`: Used to determine the number of wavelength pixels on the detector for a given spectrum (default: 0.14 nm/pix)
- `Spatial Aperture`: Number of spatial pixels (default: 13)
- `Sky Brightness`: Amount of sky brightness at MLO, used to determine sky noise (default: 21.6 mag/arcsec^2)
- `Read Noise`: Read noise of the QHYCCD detector (default: 2.3 e)
- `Pix Scale`: The scaling factor to transition between arcseconds and detector pixels (default: 0.8 arcsec/pix).
- `Lens Throughput`: Constant lens throughput value used for total throughput calculation (default: 0.99).
- `Telescope Diameter` (mm): Diameter of the telescope the spectrograph is mounted on (default: 1250 mm).
- `Temperature` (&deg;C): Used to infer the dark current contribution to noise from the DC vs temp curve for the QHYCCD detector (default: -10&deg; C).

#### 4. Output Results
