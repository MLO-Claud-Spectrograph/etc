from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from matplotlib import pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
import matplotlib as mpl
# Pick the first available preferred style (fallback to default)
for _style in ("seaborn-whitegrid", "seaborn", "ggplot", "classic", "default"):
    if _style in plt.style.available:
        plt.style.use(_style)
        break
else:
    plt.style.use("default")

mpl.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["DejaVu Sans", "Arial"],
    "font.size": 11,
    "axes.titlesize": 14,
    "axes.labelsize": 12,
    "legend.frameon": False,
})

# GUI palette and background
GUI_BG = "#000020"
ACCENT_COLORS = ["#f7f702"]
PREFERRED_FONTS = ["Helvetica", "DejaVu Sans", "Liberation Sans", "Arial", "Nimbus Sans", "fixed"]
AIRMass_MODEL_LABELS = {
    "average": "Average",
    "ctio": "Cerro Tololo",
    "kpno": "Kitt Peak",
    "lapalma": "Roque de Los Muchachos",
    "mko": "Mauna Kea",
    "mtham": "Lick",
    "paranal": "ESO (Paranal)",
    "apo": "Apache Point",
}
AIRMass_DISPLAY_TO_KEY = {label: key for key, label in AIRMass_MODEL_LABELS.items()}

from etc_core import ETCCalculator, get_default_spectrum_file


class PlaceholderEntry(ttk.Entry):
    def __init__(self, master, placeholder: str, **kwargs):
        super().__init__(master, **kwargs)
        self.placeholder = placeholder
        self.default_fg = "#000000"
        self.placeholder_fg = "#808080"
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

    def set_placeholder(self, placeholder: str) -> None:
        showing_placeholder = self.cget("foreground") == self.placeholder_fg and self.get() == self.placeholder
        self.placeholder = placeholder
        if showing_placeholder or not self.get().strip():
            self._show_placeholder()

    def set_value(self, value: str) -> None:
        self.delete(0, tk.END)
        self.insert(0, value)
        self.configure(foreground=self.default_fg)


class SquareToggle(ttk.Frame):
    """Square toggle with colored fill when on, white when off and a black checkmark when on."""
    def __init__(self, master, text, var: tk.BooleanVar, color="#f7f702"):
        super().__init__(master, style='TFrame')
        self.var = var
        self.color = color
        self._bg = GUI_BG
        self.canvas = tk.Canvas(self, width=18, height=18, highlightthickness=0, bg=self._bg, bd=0)
        self.rect = self.canvas.create_rectangle(2, 2, 16, 16, fill=(self.color if self.var.get() else "#ffffff"), outline=self.color)
        # create a checkmark (hidden when off)
        self.check = self.canvas.create_line(5, 10, 8, 13, 14, 5, width=2, fill='black', capstyle=tk.ROUND, joinstyle=tk.ROUND)
        if not self.var.get():
            self.canvas.itemconfig(self.check, state='hidden')
        self.canvas.pack(side=tk.LEFT)
        self.label = ttk.Label(self, text=text)
        self.label.pack(side=tk.LEFT, padx=(6, 0))
        # Bind click and disable hover color changes
        for w in (self.canvas, self.label, self):
            w.bind("<Button-1>", self._toggle)
            w.bind("<Enter>", lambda e: "break")
            w.bind("<Leave>", lambda e: "break")
        try:
            self.var.trace_add("write", lambda *a: self._update())
        except AttributeError:
            self.var.trace("w", lambda *a: self._update())
        self._update()

    def _update(self):
        fill = self.color if self.var.get() else "#ffffff"
        self.canvas.itemconfig(self.rect, fill=fill)
        self.canvas.itemconfig(self.check, state='normal' if self.var.get() else 'hidden')

    def _toggle(self, _event=None):
        self.var.set(not self.var.get())


class ETCGui(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("MLO Spectrograph ETC")
        self.geometry("980x760")

        # Apply ttk styles and fonts
        style = ttk.Style(self)
        # pick first available preferred font and apply
        chosen_font = PREFERRED_FONTS[-1]
        try:
            default_font = tkfont.nametofont("TkDefaultFont")
            for f in PREFERRED_FONTS:
                default_font.configure(family=f)
                chosen_font = f
                break
        except Exception:
            pass
        style.configure('.', font=(chosen_font, 11), foreground='white')
        style.configure('TFrame', background=GUI_BG)
        style.configure('TLabel', background=GUI_BG, foreground='white')
        style.configure('TLabelframe', background=GUI_BG)
        style.configure('TLabelframe.Label', background=GUI_BG, foreground='white')
        style.configure('TEntry', fieldbackground='#ffffff', foreground='#000000')
        style.configure('TCombobox', fieldbackground='#ffffff', foreground='#000000')
        style.configure('NoOutline.TCombobox', fieldbackground=GUI_BG, foreground='white', relief='flat', borderwidth=0)
        self.configure(bg=GUI_BG)

        self.calc = ETCCalculator()

        self.spectrum_path = tk.StringVar(value="")
        self.camera_model = tk.StringVar(value=self.calc.available_camera_models[0])
        self.grating = tk.StringVar(value="1229")
        default_airmass_key = self.calc.available_airmass_models[0]
        self.airmass = tk.StringVar(value=self._airmass_display_label(default_airmass_key))
        self._read_noise_default_placeholder = f"{self.calc.default_read_noise_for_camera(self.camera_model.get()):.1f}"

        self.toggle_vars = {
            "detector": tk.BooleanVar(value=True),
            "grating": tk.BooleanVar(value=True),
            "fiber": tk.BooleanVar(value=True),
            "airmass": tk.BooleanVar(value=True),
            "lens": tk.BooleanVar(value=True),
        }

        self._build_ui()
        # Prompt user to choose reference spectrum on startup (starts in 'data' dir)
        self.after(100, self._prompt_for_spectrum)

    def _build_ui(self):
        root = ttk.Frame(self, padding=12)
        root.pack(fill=tk.BOTH, expand=True)

        path_frame = ttk.LabelFrame(root, text="Spectrum:")
        path_frame.pack(fill=tk.X, pady=6)
        # picker centered at top
        picker_frame = ttk.Frame(path_frame)
        picker_frame.pack(fill=tk.X, pady=(6, 0))
        self.path_entry = tk.Entry(picker_frame, textvariable=self.spectrum_path, fg='#000000', bg='#ffffff', insertbackground='#000000', relief='solid', bd=1, width=60)
        self.path_entry.pack(side=tk.LEFT, padx=6, pady=6)
        self.path_entry.bind("<FocusIn>", self._on_spectrum_focus_in)
        self.path_entry.bind("<KeyRelease>", self._on_spectrum_key_release)
        tk.Button(picker_frame, text="Browse", command=lambda: self._browse(initial_dir=None), bg=GUI_BG, fg='white', activebackground=GUI_BG, activeforeground='white', bd=0).pack(side=tk.LEFT, padx=6)

        # Spectrum preview removed per user request
        self._small_fig = None
        self._small_ax = None
        self._small_canvas = None

        mode_frame = ttk.LabelFrame(root, text="Instrument options")
        mode_frame.pack(fill=tk.X, pady=6)

        ttk.Label(mode_frame, text="Grating:").grid(row=0, column=0, padx=6, pady=6, sticky=tk.W)
        ttk.Combobox(mode_frame, textvariable=self.grating, values=[str(g) for g in self.calc.available_gratings], state="readonly", width=12).grid(row=0, column=1, padx=6, pady=6)

        ttk.Label(mode_frame, text="Airmass model:").grid(row=0, column=2, padx=6, pady=6, sticky=tk.W)
        ttk.Combobox(mode_frame, textvariable=self.airmass, values=[self._airmass_display_label(model) for model in self.calc.available_airmass_models], state="readonly", width=28).grid(row=0, column=3, padx=6, pady=6)

        ttk.Label(mode_frame, text="Camera model:").grid(row=0, column=4, padx=6, pady=6, sticky=tk.W)
        camera_combo = ttk.Combobox(
            mode_frame,
            textvariable=self.camera_model,
            values=self.calc.available_camera_models,
            state="readonly",
            width=12,
        )
        camera_combo.grid(row=0, column=5, padx=6, pady=6)
        camera_combo.bind("<<ComboboxSelected>>", self._on_camera_model_changed)

        toggles_frame = ttk.LabelFrame(root, text="Included Throughput Factors:")
        toggles_frame.pack(fill=tk.X, pady=6)
        for i, (name, var) in enumerate(self.toggle_vars.items()):
            toggle = SquareToggle(toggles_frame, name.capitalize(), var, color=ACCENT_COLORS[0])
            toggle.grid(row=0, column=i, padx=8, pady=6, sticky=tk.W)

        fields_frame = ttk.LabelFrame(root, text="SNR inputs")
        fields_frame.pack(fill=tk.X, pady=6)

        self.entries = {}
        specs = [
            ("exp_time", "", "s", "Exposure Time:"),
            ("z", "", "", "Redshift:"),
            ("wave_centers_nm", "", "nm", "Wave Centers (comma-separated):"),
            ("binsize_nm", "", "nm", "Bin Size:"),
            ("dispersion_nm_per_pix", "0.14", "nm/pix", "Dispersion:"),
            ("spacial_aperture_pix", "13", "pix", "Spacial Aperture:"),
            ("sky_brightness", "21.6", "mag/arcsec^2", "Sky Brightness:"),
            ("read_noise_e", self._read_noise_default_placeholder, "e-", "Read Noise:"),
            ("pix_scale", "0.8", "arcsec/pix", "Pix Scale:"),
            ("lens", "0.99", "", "Lens Throughput:"),
            ("t_diam_mm", "1250", "mm", "Telescope Diameter:"),
            ("temp_c", "-10", "C", "Temperature:"),
        ]

        for i, (key, placeholder, unit, display) in enumerate(specs):
            r, c = divmod(i, 4)
            ttk.Label(fields_frame, text=display).grid(row=r * 2, column=c, padx=6, pady=(6, 0), sticky=tk.W)
            holder = ttk.Frame(fields_frame)
            holder.grid(row=r * 2 + 1, column=c, padx=6, pady=(0, 6), sticky=tk.W)
            entry = PlaceholderEntry(holder, placeholder, width=18, foreground='black')
            entry.pack(side=tk.LEFT)
            if unit:
                ttk.Label(holder, text=unit).pack(side=tk.LEFT, padx=(6, 0))
            self.entries[key] = entry

        btn_frame = ttk.Frame(root)
        btn_frame.pack(fill=tk.X, pady=10)
        tk.Button(btn_frame, text="Compute SNR", command=self._compute, bg=GUI_BG, fg='white', activebackground=GUI_BG, activeforeground='white', bd=0).pack(side=tk.LEFT, padx=6)
        tk.Button(btn_frame, text="Plot throughput", command=self._plot_throughput, bg=GUI_BG, fg='white', activebackground=GUI_BG, activeforeground='white', bd=0).pack(side=tk.LEFT, padx=6)

        out_frame = ttk.LabelFrame(root, text="Results")
        out_frame.pack(fill=tk.BOTH, expand=True)
        self.output = tk.Text(out_frame, wrap=tk.WORD, height=16, bg=GUI_BG, fg='white', insertbackground='white')
        self.output.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

    def _browse(self, initial_dir: str | None = None):
        # Custom file browser so dialog widget colors can be controlled
        d = tk.Toplevel(self)
        d.title("Select spectrum file")
        d.configure(bg=GUI_BG)
        d.transient(self)
        d.grab_set()

        cur_dir = Path(initial_dir) if initial_dir else (Path(self.spectrum_path.get()) if self.spectrum_path.get() else Path.cwd())
        dir_frame = ttk.Frame(d)
        dir_frame.pack(fill=tk.X, padx=8, pady=8)
        tk.Label(dir_frame, text="Directory:", fg='#000000', bg=GUI_BG).pack(side=tk.LEFT)
        dir_var = tk.StringVar(value=str(cur_dir))
        dir_entry = tk.Entry(dir_frame, textvariable=dir_var, fg='#000000', bg='#ffffff')
        dir_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=6)

        type_frame = ttk.Frame(d)
        type_frame.pack(fill=tk.X, padx=8)
        tk.Label(type_frame, text="Files of type:", fg='white', bg=GUI_BG, relief='flat').pack(side=tk.LEFT)
        filetypes = ["All files (*.*)", "FITS (*.fits)", "Text (*.txt)"]
        type_var = tk.StringVar(value=filetypes[0])
        type_combo = ttk.Combobox(type_frame, textvariable=type_var, values=filetypes, state='readonly', width=20, style='NoOutline.TCombobox')
        type_combo.pack(side=tk.LEFT, padx=6)

        list_frame = ttk.Frame(d)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        scrollbar = tk.Scrollbar(list_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        listbox = tk.Listbox(list_frame, yscrollcommand=scrollbar.set, selectmode=tk.SINGLE, bg='white', fg='black', highlightthickness=0)
        listbox.pack(fill=tk.BOTH, expand=True)
        scrollbar.config(command=listbox.yview)

        def update_file_list(_=None):
            listbox.delete(0, tk.END)
            p = Path(dir_var.get())
            if not p.exists():
                return
            pattern = '*'
            sel = type_var.get()
            if 'FITS' in sel:
                pattern = '*.fits'
            elif 'Text' in sel:
                pattern = '*.txt'
            for f in sorted(p.glob(pattern)):
                if f.is_file():
                    listbox.insert(tk.END, str(f.name))

        def change_dir(_=None):
            update_file_list()

        dir_entry.bind("<Return>", lambda e: change_dir())
        type_combo.bind("<<ComboboxSelected>>", update_file_list)

        update_file_list()

        btn_frame = ttk.Frame(d)
        btn_frame.pack(fill=tk.X, padx=8, pady=8)
        def do_open():
            sel = listbox.curselection()
            if not sel:
                return
            name = listbox.get(sel[0])
            path = str(Path(dir_var.get()) / name)
            self.spectrum_path.set(path)
            self.path_entry.config(fg='#000000')
            try:
                self._update_small_spectrum_plot()
            except Exception:
                pass
            d.destroy()

        def do_cancel():
            d.destroy()

        tk.Button(btn_frame, text="Open", command=do_open, bg=GUI_BG, fg='white', bd=0, activebackground=GUI_BG, activeforeground='white').pack(side=tk.RIGHT, padx=6)
        tk.Button(btn_frame, text="Cancel", command=do_cancel, bg=GUI_BG, fg='white', bd=0, activebackground=GUI_BG, activeforeground='white').pack(side=tk.RIGHT)

        d.wait_window()

    def _prompt_for_spectrum(self):
        # Force user to choose a reference spectrum at startup. Start in repo 'data' directory.
        data_dir = Path(__file__).resolve().parents[1] / "data" / "SN_ref_spectra"
        while not self.spectrum_path.get():
            self._browse(initial_dir=str(data_dir) if data_dir.exists() else None)
            if not self.spectrum_path.get():
                messagebox.showwarning("Reference spectrum required", "Please select a reference spectrum file to continue.")

    def _on_spectrum_focus_in(self, _event=None):
        if self.path_entry.cget('fg') == '#ffffff':
            self.path_entry.delete(0, tk.END)
            self.path_entry.config(fg='#000000')

    def _on_spectrum_key_release(self, _event=None):
        if self.path_entry.get() and self.path_entry.cget('fg') == '#ffffff':
            self.path_entry.config(fg='#000000')

    def _airmass_display_label(self, model_key: str) -> str:
        return AIRMass_MODEL_LABELS.get(model_key, model_key)

    def _airmass_model_key(self, display_label: str) -> str:
        return AIRMass_DISPLAY_TO_KEY.get(display_label, display_label)

    def _on_camera_model_changed(self, _event=None):
        self._read_noise_default_placeholder = f"{self.calc.default_read_noise_for_camera(self.camera_model.get()):.1f}"
        self.entries["read_noise_e"].set_placeholder(self._read_noise_default_placeholder)
        self.entries["read_noise_e"].set_value(self._read_noise_default_placeholder)

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
                "camera_model": self.camera_model.get(),
                "grat_master_num": int(self.grating.get()),
                "airmass_model": self._airmass_model_key(self.airmass.get()),
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
        self.output.insert(tk.END, f"Camera model: {result['meta']['camera_model']}\n")
        self.output.insert(tk.END, f"Read noise: {result['meta']['read_noise_e']:.2f} e-\n")
        self.output.insert(tk.END, f"Grating: {result['meta']['grating']}\n")
        self.output.insert(tk.END, f"Airmass model: {self._airmass_display_label(result['meta']['airmass_model'])}\n\n")

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
                camera_model=params["camera_model"],
                grat_master_num=params["grat_master_num"],
                airmass_model=params["airmass_model"],
                lens=params["lens"],
                throughput_toggles=params["throughput_toggles"],
            )
        except Exception as exc:
            messagebox.showerror("Plot error", str(exc))
            return

        fig, ax = plt.subplots(figsize=(10, 6))
        cmap = plt.get_cmap("tab10")
        comp_names = ["detector", "grating", "fiber", "airmass", "lens"]
        for i, name in enumerate(comp_names):
            if params["throughput_toggles"].get(name, True):
                ax.plot(wave, components[name], label=name.capitalize(), color=cmap(i % 10), ls='--', alpha=0.9, linewidth=1.8)
        ax.plot(wave, components["total"], label="Total", linewidth=3.0, color="#0abd78")

        binsize = params.get("binsize", None)
        centers = params.get("wave_centers", [])
        for center in centers:
            ax.axvline(center, color="#000000", linestyle="-", linewidth=1.2, alpha=0.9)
            if binsize is not None:
                left = center - binsize / 2.0
                right = center + binsize / 2.0
                ax.axvline(left, color="#7f7f7f", linestyle="--", linewidth=0.9, alpha=0.7)
                ax.axvline(right, color="#7f7f7f", linestyle="--", linewidth=0.9, alpha=0.7)
        try:
            ytop = ax.get_ylim()[1]
            for center in centers:
                ax.text(center-3, ytop * 0.2, 'Wave Bin Center', rotation=90, va='top', ha='right', color='#000000', fontsize=8)
        except Exception:
            pass

        ax.set_xlabel("Wavelength (nm)")
        ax.set_ylabel("Throughput")
        ax.set_xlim(400, 900)
        ax.legend()
        fig.tight_layout()
        plt.show()


if __name__ == "__main__":
    app = ETCGui()
    app.mainloop()
