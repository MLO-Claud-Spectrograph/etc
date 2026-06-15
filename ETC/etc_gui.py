from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from matplotlib import pyplot as plt

from etc_core import ETCCalculator, get_default_spectrum_file


class PlaceholderEntry(ttk.Entry):
    def __init__(self, master, placeholder: str, **kwargs):
        super().__init__(master, **kwargs)
        self.placeholder = placeholder
        self.default_fg = "black"
        self.placeholder_fg = "gray"
        self._show_placeholder()
        self.bind("<FocusIn>", self._clear_placeholder)
        self.bind("<FocusOut>", self._restore_if_empty)

    def _show_placeholder(self):
        self.configure(foreground=self.placeholder_fg)
        self.delete(0, tk.END)
        self.insert(0, self.placeholder)

    def _clear_placeholder(self, _event=None):
        if self.get() == self.placeholder and self.cget("foreground") == self.placeholder_fg:
            self.delete(0, tk.END)
            self.configure(foreground=self.default_fg)

    def _restore_if_empty(self, _event=None):
        if not self.get().strip():
            self._show_placeholder()

    def value(self) -> str:
        val = self.get().strip()
        return "" if val == self.placeholder and self.cget("foreground") == self.placeholder_fg else val


class ETCGui(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("MLO Spectrograph ETC")
        self.geometry("980x760")

        self.calc = ETCCalculator()

        self.spectrum_path = tk.StringVar(value=str(get_default_spectrum_file()))
        self.grating = tk.StringVar(value="1229")
        self.airmass = tk.StringVar(value=self.calc.available_airmass_models[0])

        self.toggle_vars = {
            "detector": tk.BooleanVar(value=True),
            "grating": tk.BooleanVar(value=True),
            "fiber": tk.BooleanVar(value=True),
            "airmass": tk.BooleanVar(value=True),
            "lens": tk.BooleanVar(value=True),
        }

        self._build_ui()

    def _build_ui(self):
        root = ttk.Frame(self, padding=12)
        root.pack(fill=tk.BOTH, expand=True)

        path_frame = ttk.LabelFrame(root, text="Spectrum file")
        path_frame.pack(fill=tk.X, pady=6)
        ttk.Entry(path_frame, textvariable=self.spectrum_path).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=6, pady=6)
        ttk.Button(path_frame, text="Browse", command=self._browse).pack(side=tk.LEFT, padx=6)

        mode_frame = ttk.LabelFrame(root, text="Instrument options")
        mode_frame.pack(fill=tk.X, pady=6)

        ttk.Label(mode_frame, text="Grating").grid(row=0, column=0, padx=6, pady=6, sticky=tk.W)
        ttk.Combobox(mode_frame, textvariable=self.grating, values=[str(g) for g in self.calc.available_gratings], state="readonly", width=12).grid(row=0, column=1, padx=6, pady=6)

        ttk.Label(mode_frame, text="Airmass model").grid(row=0, column=2, padx=6, pady=6, sticky=tk.W)
        ttk.Combobox(mode_frame, textvariable=self.airmass, values=self.calc.available_airmass_models, state="readonly", width=18).grid(row=0, column=3, padx=6, pady=6)

        toggles_frame = ttk.LabelFrame(root, text="Throughput components (checkbox = included)")
        toggles_frame.pack(fill=tk.X, pady=6)
        for i, (name, var) in enumerate(self.toggle_vars.items()):
            ttk.Checkbutton(toggles_frame, text=name.capitalize(), variable=var).grid(row=0, column=i, padx=8, pady=6, sticky=tk.W)

        fields_frame = ttk.LabelFrame(root, text="SNR inputs")
        fields_frame.pack(fill=tk.X, pady=6)

        self.entries = {}
        specs = [
            ("exp_time", "7200"),
            ("z", "0.05"),
            ("wave_centers_nm", "600,700"),
            ("binsize_nm", "5"),
            ("dispersion_nm_per_pix", "0.14"),
            ("spacial_aperture_pix", "13"),
            ("sky_brightness", "21.6"),
            ("read_noise_e", "2.3"),
            ("pix_scale", "0.8"),
            ("lens", "0.99"),
            ("t_diam_mm", "1250"),
            ("temp_c", "-10"),
        ]

        for i, (key, default) in enumerate(specs):
            r, c = divmod(i, 4)
            ttk.Label(fields_frame, text=key).grid(row=r * 2, column=c, padx=6, pady=(6, 0), sticky=tk.W)
            entry = PlaceholderEntry(fields_frame, default, width=22)
            entry.grid(row=r * 2 + 1, column=c, padx=6, pady=(0, 6), sticky=tk.W)
            self.entries[key] = entry

        btn_frame = ttk.Frame(root)
        btn_frame.pack(fill=tk.X, pady=10)
        ttk.Button(btn_frame, text="Compute SNR", command=self._compute).pack(side=tk.LEFT, padx=6)
        ttk.Button(btn_frame, text="Plot throughput", command=self._plot_throughput).pack(side=tk.LEFT, padx=6)

        out_frame = ttk.LabelFrame(root, text="Results")
        out_frame.pack(fill=tk.BOTH, expand=True)
        self.output = tk.Text(out_frame, wrap=tk.WORD, height=16)
        self.output.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

    def _browse(self):
        path = filedialog.askopenfilename(initialdir=str(Path(self.spectrum_path.get()).parent))
        if path:
            self.spectrum_path.set(path)

    def _read_inputs(self):
        try:
            wave_centers = [float(x.strip()) for x in self.entries["wave_centers_nm"].value().split(",") if x.strip()]
            return {
                "exp_time": float(self.entries["exp_time"].value()),
                "spectrum_file": self.spectrum_path.get(),
                "z": float(self.entries["z"].value()),
                "wave_centers": wave_centers,
                "binsize": float(self.entries["binsize_nm"].value()),
                "dispersion": float(self.entries["dispersion_nm_per_pix"].value()),
                "spacial_aperture": float(self.entries["spacial_aperture_pix"].value()),
                "sky_brightness": float(self.entries["sky_brightness"].value()),
                "read_noise_e": float(self.entries["read_noise_e"].value()),
                "pix_scale": float(self.entries["pix_scale"].value()),
                "grat_master_num": int(self.grating.get()),
                "airmass_model": self.airmass.get(),
                "lens": float(self.entries["lens"].value()),
                "t_diam": float(self.entries["t_diam_mm"].value()),
                "temp": float(self.entries["temp_c"].value()),
                "throughput_toggles": {k: v.get() for k, v in self.toggle_vars.items()},
            }
        except ValueError as exc:
            raise ValueError(f"Invalid input value: {exc}") from exc

    def _compute(self):
        try:
            result = self.calc.get_SNR_from_spectrum(**self._read_inputs())
        except Exception as exc:
            messagebox.showerror("SNR error", str(exc))
            return

        self.output.delete("1.0", tk.END)
        self.output.insert(tk.END, f"Grating: {result['meta']['grating']}\n")
        self.output.insert(tk.END, f"Airmass model: {result['meta']['airmass_model']}\n\n")

        for row in result["bins"]:
            self.output.insert(
                tk.END,
                (
                    f"{row.wave_center_nm:.1f} nm\n"
                    f"  Source counts: {row.source_counts:.3f}\n"
                    f"  Sky counts: {row.sky_counts:.3f}\n"
                    f"  SNR: {row.snr:.3f}\n"
                    f"  Mean throughput: total={row.component_averages['total']:.3f}, "
                    f"det={row.component_averages['detector']:.3f}, grat={row.component_averages['grating']:.3f}, "
                    f"fib={row.component_averages['fiber']:.3f}, air={row.component_averages['airmass']:.3f}, "
                    f"lens={row.component_averages['lens']:.3f}\n\n"
                ),
            )

    def _plot_throughput(self):
        try:
            params = self._read_inputs()
            spec = self.calc.load_spectrum(params["spectrum_file"], params["z"])
            wave = spec["wave"]
            components = self.calc.get_throughput_components(
                wave,
                grat_master_num=params["grat_master_num"],
                airmass_model=params["airmass_model"],
                lens=params["lens"],
                throughput_toggles=params["throughput_toggles"],
            )
        except Exception as exc:
            messagebox.showerror("Plot error", str(exc))
            return

        plt.figure(figsize=(10, 6))
        for name in ["detector", "grating", "fiber", "airmass", "lens"]:
            plt.plot(wave, components[name], label=name.capitalize(), alpha=0.8)
        plt.plot(wave, components["total"], label="Total", linewidth=2.8, color="black")
        plt.xlabel("Wavelength (nm)")
        plt.ylabel("Throughput")
        plt.title("Throughput Components and Total")
        plt.legend()
        plt.tight_layout()
        plt.show()


if __name__ == "__main__":
    app = ETCGui()
    app.mainloop()
