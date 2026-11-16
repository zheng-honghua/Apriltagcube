"""Windows editor for the shared AprilTag STEP and 3MF exporter."""

import json
import math
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from exporter import DATA, export_model


INITIAL_YAW = -0.63
INITIAL_PITCH = 0.48
INK = "#12292b"
MUTED = "#526668"
ACCENT = "#00574d"
PAPER = "#edf5f1"
LINE = "#d6e5df"


class CubePreview(tk.Canvas):
    def __init__(self, parent):
        super().__init__(parent, background=PAPER, highlightthickness=1, highlightbackground=LINE)
        self.yaw, self.pitch = INITIAL_YAW, INITIAL_PITCH
        self.family, self.ratio, self.ids = next(iter(DATA["families"].values())), 0.8, [None] * 6
        self.bind("<Configure>", lambda _: self.redraw())
        self.bind("<ButtonPress-1>", self.start_drag)
        self.bind("<B1-Motion>", self.drag)
        self.configure(cursor="fleur")

    def start_drag(self, event):
        self.drag_origin = (event.x, event.y, self.yaw, self.pitch)

    def drag(self, event):
        x, y, yaw, pitch = self.drag_origin
        self.yaw = yaw + (event.x - x) * 0.012
        self.pitch = max(-1.56, min(1.56, pitch + (event.y - y) * 0.009))
        self.redraw()

    def reset_view(self):
        self.yaw, self.pitch = INITIAL_YAW, INITIAL_PITCH
        self.redraw()

    def redraw(self):
        self.delete("all")
        width, height = self.winfo_width(), self.winfo_height()
        for x in range((width // 2) % 24, width, 24):
            self.create_line(x, 0, x, height, fill=LINE)
        for y in range((height // 2) % 24, height, 24):
            self.create_line(0, y, width, y, fill=LINE)
        self.create_text(15, 14, anchor="nw", text="拖动旋转", fill=MUTED)
        scale = min(width, height) * 0.46
        cy, sy = math.cos(self.yaw), math.sin(self.yaw)
        cp, sp = math.cos(self.pitch), math.sin(self.pitch)
        view = (sy * cp, cy * cp, sp)
        horizontal, vertical = (-cy, sy, 0), (-sy * sp, -cy * sp, cp)

        for face, tag_id in zip(DATA["faces"], self.ids, strict=True):
            normal, right, up = (face[key] for key in ("normal", "right", "up"))
            if math.sumprod(normal, view) <= 1e-8:
                continue

            def quad(left, top, right_edge, bottom):
                vertices = []
                for u, v in [(left, top), (right_edge, top), (right_edge, bottom), (left, bottom)]:
                    point = [n * 0.5 + r * u + t * v for n, r, t in zip(normal, right, up)]
                    vertices.extend((width / 2 + scale * math.sumprod(point, horizontal),
                                     height / 2 - scale * math.sumprod(point, vertical)))
                return vertices

            shade = round(255 * min(1, 0.79 + 0.20 * max(0, math.sumprod(normal, (-0.25, 0.62, 0.76)))))
            self.create_polygon(*quad(-0.5, 0.5, 0.5, -0.5), fill="#" + f"{shade:02x}" * 3,
                                outline="#a4b4af")
            if tag_id is None:
                continue
            pitch = self.ratio / self.family["width"]
            for y, row in enumerate(self.family["patterns"][tag_id]):
                for x in range(self.family["width"]):
                    if row & (1 << x):
                        left, top = x * pitch - self.ratio / 2, self.ratio / 2 - y * pitch
                        self.create_polygon(*quad(left, top, left + pitch, top - pitch), fill="#111111")


class Editor:
    def __init__(self, window):
        self.window = window
        self.worker = ThreadPoolExecutor(max_workers=1)
        self.busy = False
        self.folder = Path.home()
        self.family_name = tk.StringVar(window, value="tag36h11")
        self.cube, self.size, self.depth = [tk.StringVar(window, value=value) for value in ("60", "50", "0.8")]
        self.tags = [tk.StringVar(window, value=str(i)) for i in range(len(DATA["faces"]))]
        self.enabled = [tk.BooleanVar(window, value=True) for _ in self.tags]
        self.status = tk.StringVar(window)
        self.measurements = tk.StringVar(window)

        window.title("AprilTag 方块")
        window.geometry("1020x650")
        window.minsize(840, 560)
        window.protocol("WM_DELETE_WINDOW", self.close)
        icon = Path(__file__).with_name("AppIcon.ico")
        if icon.is_file() and window.tk.call("tk", "windowingsystem") == "win32":
            window.iconbitmap(default=str(icon))

        style = ttk.Style(window)
        style.configure("Heading.TLabel", font=("TkDefaultFont", 18, "bold"), foreground=INK)
        style.configure("Section.TLabel", font=("TkDefaultFont", 11, "bold"), foreground=INK)
        style.configure("Note.TLabel", foreground=MUTED)
        style.configure("Print.TButton", foreground=ACCENT, padding=(9, 7))

        layout = ttk.Frame(window, padding=20)
        layout.pack(fill="both", expand=True)
        preview = ttk.Frame(layout)
        preview.pack(side="left", fill="both", expand=True)
        heading = ttk.Frame(preview)
        heading.pack(fill="x", pady=(0, 12))
        ttk.Label(heading, text="AprilTag 方块", style="Heading.TLabel").pack(side="left")
        self.preview = CubePreview(preview)
        ttk.Button(heading, text="重置视角", command=self.preview.reset_view).pack(side="right")
        self.preview.pack(fill="both", expand=True)
        ttk.Label(preview, textvariable=self.measurements, style="Note.TLabel").pack(anchor="w", pady=(12, 0))

        inspector = ttk.Frame(layout, padding=(20, 0, 0, 0))
        inspector.pack(side="right", fill="y")
        self.add_parameters(inspector)
        bottom = ttk.Frame(inspector)
        bottom.pack(side="bottom", fill="x")
        self.status_label = ttk.Label(bottom, textvariable=self.status, wraplength=272, foreground=MUTED)
        self.status_label.pack(anchor="w", pady=(0, 8))
        self.step = ttk.Button(bottom, text="导出 STEP", command=lambda: self.save("step"))
        self.step.pack(side="left")
        self.print_3mf = ttk.Button(bottom, text="导出打印 3MF", command=lambda: self.save("3mf"),
                                    style="Print.TButton")
        self.print_3mf.pack(side="right")
        window.bind("<Control-s>", lambda _: self.save("3mf"))
        for value in [self.family_name, self.cube, self.size, self.depth, *self.tags, *self.enabled]:
            value.trace_add("write", self.refresh)
        self.refresh()

    def add_parameters(self, inspector):
        dimensions = ttk.Frame(inspector)
        dimensions.pack(fill="x")
        ttk.Label(dimensions, text="模型尺寸", style="Section.TLabel").grid(row=0, columnspan=3, sticky="w", pady=(0, 10))
        for row, (label, value) in enumerate(zip(("方块边长", "码图边长", "嵌入深度"),
                                                  (self.cube, self.size, self.depth)), start=1):
            ttk.Label(dimensions, text=label).grid(row=row, column=0, sticky="w", pady=4)
            field = ttk.Entry(dimensions, textvariable=value, width=12, justify="right")
            field.grid(row=row, column=1, sticky="e", padx=(30, 7))
            ttk.Label(dimensions, text="mm", style="Note.TLabel").grid(row=row, column=2)
        ttk.Label(inspector, text="黑色嵌件与白色方块表面齐平。", style="Note.TLabel").pack(anchor="w", pady=(7, 0))
        ttk.Separator(inspector).pack(fill="x", pady=16)
        ttk.Label(inspector, text="码族与面", style="Section.TLabel").pack(anchor="w")
        ttk.Combobox(inspector, textvariable=self.family_name, values=tuple(DATA["families"]),
                     state="readonly").pack(fill="x", pady=8)
        ttk.Label(inspector, text="勾选需要有码的面，并填写 ID。", style="Note.TLabel").pack(anchor="w")
        grid = ttk.Frame(inspector)
        grid.pack(fill="x", pady=6)
        self.tag_fields = []
        for i, face in enumerate(DATA["faces"]):
            row, column = divmod(i, 2)
            ttk.Checkbutton(grid, text=face["label"], variable=self.enabled[i]).grid(
                row=row, column=column * 2, padx=(0, 6), pady=4, sticky="w"
            )
            entry = ttk.Entry(grid, width=7, textvariable=self.tags[i], justify="right")
            entry.grid(row=row, column=column * 2 + 1, padx=(0, 14), sticky="w")
            self.tag_fields.append(entry)

    @property
    def family(self):
        return DATA["families"][self.family_name.get()]

    def face_ids(self):
        output = []
        for active, raw in zip(self.enabled, self.tags):
            try:
                value = int(raw.get())
            except ValueError:
                value = -1
            output.append(value if active.get() and 0 <= value < len(self.family["patterns"]) else None)
        return output

    def settings(self):
        try:
            cube, size, depth = (float(v.get().strip().replace(",", ".")) for v in (self.cube, self.size, self.depth))
        except ValueError as error:
            raise ValueError("请输入有效的毫米尺寸。") from error
        if not 0.1 <= cube <= 100_000 or not 0.1 <= size <= cube:
            raise ValueError("方块边长需为 0.1–100,000 mm，且码图边长需在 0.1 mm 与方块边长之间。")
        if not math.isfinite(depth) or depth < 0.001:
            raise ValueError("嵌入深度至少为 0.001 mm。")
        white_margin = size / self.family["width"] if self.family_name.get() == "tag36h11" else 0
        if depth + 0.001 > (cube - size) / 2 + white_margin:
            raise ValueError("嵌入深度过大，请减小码图或嵌入深度。")
        ids = self.face_ids()
        if not any(active.get() for active in self.enabled):
            raise ValueError("至少勾选一个面。")
        if any(active.get() and tag is None for active, tag in zip(self.enabled, ids)):
            raise ValueError(f"已勾选面的 ID 必须在 0–{len(self.family['patterns']) - 1} 之间。")
        return {"family": self.family_name.get(), "cube": cube, "size": size, "depth": depth, "ids": ids}

    def refresh(self, *_):
        for active, field in zip(self.enabled, self.tag_fields):
            field.state(["!disabled" if active.get() else "disabled"])
        self.preview.family, self.preview.ids = self.family, self.face_ids()
        try:
            settings = self.settings()
        except ValueError as error:
            state, message = "disabled", str(error)
            self.measurements.set("")
        else:
            cube, size, depth = (settings[key] for key in ("cube", "size", "depth"))
            self.preview.ratio = size / cube
            detected = size * self.family["border"] / self.family["width"]
            self.measurements.set(f"方块 {cube:.6g} mm    ·    码图 {size:.6g} mm    ·    检测边长 {detected:.6g} mm")
            state = "!disabled"
            message = ("嵌件太薄时可能被切片省略。0.2 mm 层高可先试 0.8 mm 深度。"
                       if depth < 0.4 else "可用 Bambu Studio 导入 3MF，为黑白两部分分配耗材。")
        self.preview.redraw()
        self.status.set("正在导出…" if self.busy else message)
        for button in (self.step, self.print_3mf):
            button.state(["disabled" if self.busy else state])

    def save(self, extension):
        if self.busy:
            return
        try:
            settings = self.settings()
        except ValueError:
            self.refresh()
            return
        path = filedialog.asksaveasfilename(
            parent=self.window, title=f"导出 {extension.upper()}", initialdir=self.folder,
            initialfile=f"AprilTag_{settings['family']}_{settings['cube']:g}mm.{extension}",
            defaultextension=f".{extension}", filetypes=[(extension.upper(), f"*.{extension}")],
        )
        if not path:
            return
        output = Path(path)
        accepted = {".step", ".stp"} if extension == "step" else {".3mf"}
        if output.suffix.lower() not in accepted:
            messagebox.showerror("文件扩展名", f"请使用 .{extension} 文件名。", parent=self.window)
            return
        self.folder = output.parent
        self.busy = True
        self.refresh()
        job = self.worker.submit(export_model, settings, output)
        self.window.after(40, self.finish_export, job, output)

    def finish_export(self, job, output):
        if not job.done():
            self.window.after(40, self.finish_export, job, output)
            return
        self.busy = False
        self.refresh()
        try:
            job.result()
        except Exception as error:
            messagebox.showerror("导出失败", str(error), parent=self.window)
        else:
            self.status.set(f"已导出 {output.name}")

    def close(self):
        if not self.busy:
            self.worker.shutdown()
            self.window.destroy()


def main():
    window = tk.Tk()
    Editor(window)
    window.mainloop()


if __name__ == "__main__":
    main()
