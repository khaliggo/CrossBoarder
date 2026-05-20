"""Desktop GUI for the KorдонPlan border crossing planner."""

from __future__ import annotations

import threading
import queue
from datetime import datetime
from pathlib import Path
from tkinter import BOTH, END, LEFT, RIGHT, X, Canvas, StringVar, Tk, messagebox, simpledialog
from tkinter import ttk

from analytics import average_wait_by_crossing_day_month, build_load_profile, recommend_trip, summarise_dataset
from data_loader import DATA_DIR, download_archive_resources, download_current_resources, list_csv_files, load_records
from report import (
    REPORTS_DIR,
    create_bar_chart,
    format_hours,
    format_load_profile,
    format_recommendations,
    format_summary,
    save_csv_table,
    save_text_report,
)


DIRECTION_OPTIONS = {
    "Виїзд з України": "виїзд",
    "В'їзд в Україну": "в'їзд",
    "Усі напрямки": None,
}

VEHICLE_OPTIONS = {
    "Вантажівка": "вантажівка",
    "Автобус": "автобус",
    "Усі типи": None,
}


class BorderPlannerApp(Tk):
    """Tkinter application that wraps the analytics modules."""

    def __init__(self) -> None:
        super().__init__()
        self.title("КордонПлан")
        self.geometry("1240x780")
        self.minsize(1060, 680)

        self.records: list[dict[str, object]] = []
        self.last_report = ""
        self.last_average_rows: list[dict[str, object]] = []
        self.busy = False
        self.task_queue: queue.Queue[tuple[str, object, object | None]] = queue.Queue()

        self.direction_var = StringVar(value="Виїзд з України")
        self.vehicle_var = StringVar(value="Вантажівка")
        self.date_var = StringVar(value=datetime.now().strftime("%Y-%m-%d"))
        self.days_var = StringVar(value="7")
        self.crossing_var = StringVar(value="")
        self.status_var = StringVar(value="Готово")

        self.cards: dict[str, ttk.Label] = {}
        self.action_buttons: list[ttk.Widget] = []

        self._configure_style()
        self._build_layout()
        self._set_empty_state()
        self.after(100, self._poll_tasks)
        if list_csv_files(DATA_DIR):
            self.after(250, self.load_data)

    def _configure_style(self) -> None:
        self.configure(bg="#eef3f1")
        style = ttk.Style(self)
        style.theme_use("clam")

        style.configure(".", font=("Segoe UI", 10), background="#eef3f1", foreground="#24312e")
        style.configure("Root.TFrame", background="#eef3f1")
        style.configure("Panel.TFrame", background="#ffffff", relief="flat")
        style.configure("Header.TFrame", background="#183e38")
        style.configure("HeaderTitle.TLabel", background="#183e38", foreground="#ffffff", font=("Segoe UI Semibold", 22))
        style.configure("HeaderSub.TLabel", background="#183e38", foreground="#cfe2dd", font=("Segoe UI", 10))
        style.configure("Section.TLabel", background="#ffffff", foreground="#183e38", font=("Segoe UI Semibold", 12))
        style.configure("Muted.TLabel", background="#ffffff", foreground="#60716d", font=("Segoe UI", 9))
        style.configure("Card.TFrame", background="#f7faf9", relief="flat")
        style.configure("CardTitle.TLabel", background="#f7faf9", foreground="#60716d", font=("Segoe UI", 9))
        style.configure("CardValue.TLabel", background="#f7faf9", foreground="#183e38", font=("Segoe UI Semibold", 16))
        style.configure("Primary.TButton", background="#1f6f5f", foreground="#ffffff", font=("Segoe UI Semibold", 10), padding=(14, 8))
        style.configure("Secondary.TButton", background="#e4eeeb", foreground="#183e38", padding=(12, 8))
        style.map("Primary.TButton", background=[("active", "#2f8876"), ("disabled", "#9fb7b1")])
        style.map("Secondary.TButton", background=[("active", "#d4e3df"), ("disabled", "#edf2f0")])
        style.configure("TCombobox", padding=6)
        style.configure("TEntry", padding=6)
        style.configure("Treeview", background="#ffffff", fieldbackground="#ffffff", rowheight=30, borderwidth=0)
        style.configure("Treeview.Heading", background="#dce9e5", foreground="#183e38", font=("Segoe UI Semibold", 10))
        style.map("Treeview", background=[("selected", "#1f6f5f")], foreground=[("selected", "#ffffff")])
        style.configure("TNotebook", background="#eef3f1", borderwidth=0)
        style.configure("TNotebook.Tab", padding=(16, 9), font=("Segoe UI Semibold", 10))

    def _build_layout(self) -> None:
        root = ttk.Frame(self, style="Root.TFrame", padding=16)
        root.pack(fill=BOTH, expand=True)

        header = ttk.Frame(root, style="Header.TFrame", padding=(22, 18))
        header.pack(fill=X)
        ttk.Label(header, text="КордонПлан", style="HeaderTitle.TLabel").pack(anchor="w")
        ttk.Label(header, text="Рекомендації для перетину кордону на основі даних еЧерги", style="HeaderSub.TLabel").pack(anchor="w", pady=(4, 0))

        content = ttk.Frame(root, style="Root.TFrame")
        content.pack(fill=BOTH, expand=True, pady=(16, 0))

        sidebar = ttk.Frame(content, style="Panel.TFrame", padding=18, width=300)
        sidebar.pack(side=LEFT, fill="y")
        sidebar.pack_propagate(False)
        self._build_sidebar(sidebar)

        workspace = ttk.Frame(content, style="Root.TFrame")
        workspace.pack(side=RIGHT, fill=BOTH, expand=True, padx=(16, 0))
        self._build_workspace(workspace)

        footer = ttk.Frame(root, style="Root.TFrame")
        footer.pack(fill=X, pady=(12, 0))
        self.progress = ttk.Progressbar(footer, mode="indeterminate", length=190)
        self.progress.pack(side=LEFT)
        ttk.Label(footer, textvariable=self.status_var, background="#eef3f1", foreground="#3e5450").pack(side=LEFT, padx=(12, 0))

    def _build_sidebar(self, parent: ttk.Frame) -> None:
        ttk.Label(parent, text="Дані", style="Section.TLabel").pack(anchor="w")
        self._add_button(parent, "Зчитати data/", self.load_data, "Primary.TButton")
        self._add_button(parent, "Скачати поточні CSV", self.download_data, "Secondary.TButton")
        self._add_button(parent, "Скачати архів CSV", self.download_archive_data, "Secondary.TButton")

        ttk.Separator(parent).pack(fill=X, pady=18)

        ttk.Label(parent, text="Параметри", style="Section.TLabel").pack(anchor="w")
        self._add_labeled_combobox(parent, "Напрямок", self.direction_var, list(DIRECTION_OPTIONS))
        self._add_labeled_combobox(parent, "Транспорт", self.vehicle_var, list(VEHICLE_OPTIONS))
        self._add_labeled_entry(parent, "Дата поїздки", self.date_var)
        self._add_labeled_entry(parent, "Днів для пошуку", self.days_var)
        self._add_labeled_entry(parent, "Пункт пропуску", self.crossing_var)

        ttk.Separator(parent).pack(fill=X, pady=18)

        ttk.Label(parent, text="Дії", style="Section.TLabel").pack(anchor="w")
        self._add_button(parent, "Підібрати маршрут", self.show_recommendations, "Primary.TButton")
        self._add_button(parent, "Середні очікування", self.show_average_waits, "Secondary.TButton")
        self._add_button(parent, "Профіль завантаженості", self.show_load_profile, "Secondary.TButton")
        self._add_button(parent, "Зберегти звіт", self.save_report, "Secondary.TButton")
        self._add_button(parent, "Зберегти CSV", self.save_average_csv, "Secondary.TButton")
        self._add_button(parent, "PNG-чарт", self.save_png_chart, "Secondary.TButton")

    def _build_workspace(self, parent: ttk.Frame) -> None:
        cards_frame = ttk.Frame(parent, style="Root.TFrame")
        cards_frame.pack(fill=X)
        self._add_card(cards_frame, "records", "Записів", "0")
        self._add_card(cards_frame, "crossings", "Пунктів", "0")
        self._add_card(cards_frame, "period", "Період", "-")
        self._add_card(cards_frame, "files", "CSV-файлів", "0")

        self.notebook = ttk.Notebook(parent)
        self.notebook.pack(fill=BOTH, expand=True, pady=(16, 0))

        self.recommendations_tab = ttk.Frame(self.notebook, style="Panel.TFrame", padding=14)
        self.average_tab = ttk.Frame(self.notebook, style="Panel.TFrame", padding=14)
        self.profile_tab = ttk.Frame(self.notebook, style="Panel.TFrame", padding=14)
        self.summary_tab = ttk.Frame(self.notebook, style="Panel.TFrame", padding=14)

        self.notebook.add(self.recommendations_tab, text="Рекомендації")
        self.notebook.add(self.average_tab, text="Середні очікування")
        self.notebook.add(self.profile_tab, text="Профіль")
        self.notebook.add(self.summary_tab, text="Підсумок")

        self._build_recommendations_tab()
        self._build_average_tab()
        self._build_profile_tab()
        self._build_summary_tab()

    def _build_recommendations_tab(self) -> None:
        top = ttk.Frame(self.recommendations_tab, style="Panel.TFrame")
        top.pack(fill=X)
        ttk.Label(top, text="Найкращі варіанти", style="Section.TLabel").pack(side=LEFT)

        columns = ("date", "weekday", "crossing", "wait", "samples")
        self.recommendations_tree = ttk.Treeview(self.recommendations_tab, columns=columns, show="headings", height=10)
        self._setup_tree(
            self.recommendations_tree,
            {
                "date": ("Дата", 105),
                "weekday": ("День", 105),
                "crossing": ("Пункт пропуску", 520),
                "wait": ("Очікування", 120),
                "samples": ("Записів", 80),
            },
        )
        self.recommendations_tree.pack(fill=BOTH, expand=True, pady=(12, 0))

    def _build_average_tab(self) -> None:
        split = ttk.Frame(self.average_tab, style="Panel.TFrame")
        split.pack(fill=BOTH, expand=True)

        left = ttk.Frame(split, style="Panel.TFrame")
        left.pack(side=LEFT, fill=BOTH, expand=True)

        columns = ("month", "weekday", "crossing", "wait", "samples")
        self.average_tree = ttk.Treeview(left, columns=columns, show="headings", height=13)
        self._setup_tree(
            self.average_tree,
            {
                "month": ("Місяць", 95),
                "weekday": ("День", 100),
                "crossing": ("Пункт пропуску", 430),
                "wait": ("Середнє", 110),
                "samples": ("Записів", 75),
            },
        )
        self.average_tree.pack(fill=BOTH, expand=True)

        right = ttk.Frame(split, style="Panel.TFrame", padding=(14, 0, 0, 0), width=320)
        right.pack(side=RIGHT, fill="y")
        right.pack_propagate(False)
        ttk.Label(right, text="Візуалізація", style="Section.TLabel").pack(anchor="w")
        self.chart_canvas = Canvas(right, width=300, height=440, bg="#ffffff", highlightthickness=0)
        self.chart_canvas.pack(fill=BOTH, expand=True, pady=(10, 0))

    def _build_profile_tab(self) -> None:
        columns = ("name", "wait", "samples")
        self.profile_tree = ttk.Treeview(self.profile_tab, columns=columns, show="headings", height=8)
        self._setup_tree(
            self.profile_tree,
            {
                "name": ("Період", 220),
                "wait": ("Середнє очікування", 160),
                "samples": ("Записів", 95),
            },
        )
        self.profile_tree.pack(fill=X)

        self.profile_text = self._add_text_box(self.profile_tab, height=12)
        self.profile_text.pack(fill=BOTH, expand=True, pady=(14, 0))

    def _build_summary_tab(self) -> None:
        self.summary_text = self._add_text_box(self.summary_tab, height=18)
        self.summary_text.pack(fill=BOTH, expand=True)

    def _add_button(self, parent: ttk.Frame, text: str, command, style: str) -> None:
        button = ttk.Button(parent, text=text, command=command, style=style)
        button.pack(fill=X, pady=(10, 0))
        self.action_buttons.append(button)

    def _add_labeled_combobox(self, parent: ttk.Frame, label: str, variable: StringVar, values: list[str]) -> None:
        ttk.Label(parent, text=label, style="Muted.TLabel").pack(anchor="w", pady=(12, 3))
        combo = ttk.Combobox(parent, textvariable=variable, values=values, state="readonly")
        combo.pack(fill=X)

    def _add_labeled_entry(self, parent: ttk.Frame, label: str, variable: StringVar) -> None:
        ttk.Label(parent, text=label, style="Muted.TLabel").pack(anchor="w", pady=(12, 3))
        entry = ttk.Entry(parent, textvariable=variable)
        entry.pack(fill=X)

    def _add_card(self, parent: ttk.Frame, key: str, title: str, value: str) -> None:
        card = ttk.Frame(parent, style="Card.TFrame", padding=(16, 12), width=190)
        card.pack(side=LEFT, fill=X, expand=True, padx=(0, 12))
        ttk.Label(card, text=title, style="CardTitle.TLabel").pack(anchor="w")
        label = ttk.Label(card, text=value, style="CardValue.TLabel")
        label.pack(anchor="w", pady=(4, 0))
        self.cards[key] = label

    def _add_text_box(self, parent: ttk.Frame, height: int):
        text = __import__("tkinter").Text(
            parent,
            height=height,
            wrap="word",
            bg="#ffffff",
            fg="#24312e",
            relief="flat",
            padx=12,
            pady=12,
            font=("Segoe UI", 10),
            insertbackground="#1f6f5f",
        )
        return text

    def _setup_tree(self, tree: ttk.Treeview, columns: dict[str, tuple[str, int]]) -> None:
        for column, (heading, width) in columns.items():
            tree.heading(column, text=heading)
            tree.column(column, width=width, anchor="w", stretch=column == "crossing")

        scrollbar = ttk.Scrollbar(tree.master, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=RIGHT, fill="y")

    def _set_empty_state(self) -> None:
        self._set_text(self.summary_text, "Завантажте CSV з папки data або скачайте поточні файли з data.gov.ua.")
        self._set_text(self.profile_text, "")
        self._draw_empty_chart()

    def _selected_direction(self) -> str | None:
        return DIRECTION_OPTIONS.get(self.direction_var.get())

    def _selected_vehicle(self) -> str | None:
        return VEHICLE_OPTIONS.get(self.vehicle_var.get())

    def _selected_date(self):
        value = self.date_var.get().strip()
        try:
            return datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError:
            messagebox.showerror("Некоректна дата", "Введіть дату у форматі YYYY-MM-DD.")
            return None

    def _selected_days(self) -> int | None:
        try:
            return max(1, min(31, int(self.days_var.get().strip())))
        except ValueError:
            messagebox.showerror("Некоректне число", "Кількість днів має бути числом від 1 до 31.")
            return None

    def _require_records(self) -> bool:
        if self.records:
            return True
        if list_csv_files(DATA_DIR):
            self.load_data()
            return False
        messagebox.showwarning("Немає CSV", "У папці data немає CSV-файлів. Скачайте дані або додайте файли вручну.")
        return False

    def _set_busy(self, busy: bool, message: str | None = None) -> None:
        self.busy = busy
        for button in self.action_buttons:
            button.configure(state="disabled" if busy else "normal")
        if busy:
            self.progress.start(12)
        else:
            self.progress.stop()
        if message:
            self.status_var.set(message)

    def _run_task(self, message: str, worker, on_success) -> None:
        if self.busy:
            return

        self._set_busy(True, message)

        def wrapper() -> None:
            try:
                result = worker()
            except Exception as exc:  # noqa: BLE001 - GUI must show any failure.
                self.task_queue.put(("error", exc, None))
                return
            self.task_queue.put(("success", result, on_success))

        threading.Thread(target=wrapper, daemon=True).start()

    def _poll_tasks(self) -> None:
        while True:
            try:
                kind, payload, callback = self.task_queue.get_nowait()
            except queue.Empty:
                break

            if kind == "success" and callback is not None:
                self._finish_task_success(payload, callback)
            elif kind == "error" and isinstance(payload, Exception):
                self._finish_task_error(payload)

        self.after(100, self._poll_tasks)

    def _finish_task_success(self, result, on_success) -> None:
        self._set_busy(False, "Готово")
        on_success(result)

    def _finish_task_error(self, error: Exception) -> None:
        self._set_busy(False, "Помилка")
        messagebox.showerror("Помилка", str(error))

    def load_data(self) -> None:
        self._run_task("Зчитую CSV з data ...", lambda: load_records(DATA_DIR), self._after_records_loaded)

    def download_data(self) -> None:
        def worker():
            downloaded = download_current_resources(DATA_DIR)
            records = load_records(DATA_DIR)
            return downloaded, records

        self._run_task("Скачую CSV з data.gov.ua ...", worker, self._after_downloaded)

    def download_archive_data(self) -> None:
        resource = simpledialog.askstring("Архів CSV", "Ресурс: queue або busQueue", initialvalue="queue", parent=self)
        if resource is None:
            return
        resource = resource.strip() or "queue"
        if resource not in {"queue", "busQueue"}:
            messagebox.showerror("Некоректний ресурс", "Введіть queue або busQueue.")
            return

        limit = simpledialog.askinteger("Архів CSV", "Скільки ревізій скачати?", initialvalue=6, minvalue=1, maxvalue=12, parent=self)
        if limit is None:
            return

        def worker():
            downloaded = download_archive_resources(resource, DATA_DIR, limit=limit)
            records = load_records(DATA_DIR)
            return downloaded, records

        self._run_task("Скачую архівні CSV ...", worker, self._after_downloaded)

    def _after_downloaded(self, result) -> None:
        downloaded, records = result
        self._after_records_loaded(records)
        self.status_var.set(f"Скачано файлів: {len(downloaded)}")

    def _after_records_loaded(self, records: list[dict[str, object]]) -> None:
        self.records = records
        summary = summarise_dataset(self.records)
        self.last_report = format_summary(summary)
        self._render_summary(summary)
        self._set_text(self.summary_text, self.last_report)
        self.notebook.select(self.summary_tab)
        self.status_var.set(f"Завантажено записів: {len(records)}")

    def _render_summary(self, summary: dict[str, object]) -> None:
        self.cards["records"].configure(text=str(summary.get("records", 0)))
        self.cards["crossings"].configure(text=str(summary.get("crossings", 0)))
        self.cards["period"].configure(text=f"{summary.get('date_from')} - {summary.get('date_to')}")
        self.cards["files"].configure(text=str(len(summary.get("source_files", []))))

    def show_recommendations(self) -> None:
        if not self._require_records():
            return
        target_date = self._selected_date()
        days = self._selected_days()
        direction = self._selected_direction() or "виїзд"
        vehicle = self._selected_vehicle()
        if target_date is None or days is None:
            return

        def worker():
            return recommend_trip(self.records, direction=direction, target_date=target_date, vehicle_group=vehicle, days_ahead=days)

        self._run_task("Розраховую рекомендації ...", worker, self._render_recommendations)

    def _render_recommendations(self, recommendations: list[dict[str, object]]) -> None:
        self._clear_tree(self.recommendations_tree)
        for item in recommendations:
            note = " *" if item.get("fallback_used") else ""
            self.recommendations_tree.insert(
                "",
                END,
                values=(
                    item.get("date"),
                    item.get("weekday_name"),
                    item.get("crossing"),
                    f"{format_hours(item.get('avg_wait_hours'))}{note}",
                    item.get("samples"),
                ),
            )
        self.last_report = format_recommendations(recommendations)
        self._set_text(self.summary_text, self.last_report)
        self.notebook.select(self.recommendations_tab)
        self.status_var.set(f"Знайдено варіантів: {len(recommendations)}")

    def show_average_waits(self) -> None:
        if not self._require_records():
            return
        direction = self._selected_direction()
        vehicle = self._selected_vehicle()

        def worker():
            return average_wait_by_crossing_day_month(self.records, direction=direction, vehicle_group=vehicle)

        self._run_task("Рахую середні очікування ...", worker, self._render_average_waits)

    def _render_average_waits(self, rows: list[dict[str, object]]) -> None:
        self.last_average_rows = rows
        self._clear_tree(self.average_tree)
        for row in rows[:300]:
            self.average_tree.insert(
                "",
                END,
                values=(
                    row.get("month_name"),
                    row.get("weekday_name"),
                    row.get("crossing"),
                    format_hours(row.get("avg_wait_hours")),
                    row.get("samples"),
                ),
            )
        self.last_report = self._average_report_text(rows)
        self._set_text(self.summary_text, self.last_report)
        self._draw_chart(rows)
        self.notebook.select(self.average_tab)
        self.status_var.set(f"Розраховано рядків: {len(rows)}")

    def show_load_profile(self) -> None:
        if not self._require_records():
            return
        direction = self._selected_direction()
        vehicle = self._selected_vehicle()
        crossing = self.crossing_var.get().strip() or None

        def worker():
            return build_load_profile(self.records, direction=direction, crossing_query=crossing, vehicle_group=vehicle)

        self._run_task("Будую профіль завантаженості ...", worker, self._render_load_profile)

    def _render_load_profile(self, profile: dict[str, object]) -> None:
        self._clear_tree(self.profile_tree)
        for item in profile.get("weekday_profile", []):
            self.profile_tree.insert("", END, values=(item.get("name"), format_hours(item.get("avg_wait_hours")), item.get("samples")))
        self.last_report = format_load_profile(profile)
        self._set_text(self.profile_text, self.last_report)
        self._set_text(self.summary_text, self.last_report)
        self.notebook.select(self.profile_tab)
        self.status_var.set("Профіль оновлено")

    def save_report(self) -> None:
        if not self.last_report:
            messagebox.showinfo("Немає звіту", "Спочатку сформуйте рекомендацію, таблицю або профіль.")
            return
        path = save_text_report(self.last_report)
        self.status_var.set(f"Звіт збережено: {path}")
        messagebox.showinfo("Збережено", f"Звіт збережено:\n{path}")

    def save_average_csv(self) -> None:
        if not self.last_average_rows:
            messagebox.showinfo("Немає таблиці", "Спочатку натисніть 'Середні очікування'.")
            return
        path = save_csv_table(
            self.last_average_rows,
            REPORTS_DIR / "average_wait_table.csv",
            ["month_name", "weekday_name", "crossing", "avg_wait_hours", "min_wait_hours", "max_wait_hours", "samples"],
        )
        self.status_var.set(f"CSV збережено: {path}")
        messagebox.showinfo("Збережено", f"CSV збережено:\n{path}")

    def save_png_chart(self) -> None:
        if not self.last_average_rows:
            messagebox.showinfo("Немає даних", "Спочатку натисніть 'Середні очікування'.")
            return
        try:
            path = create_bar_chart(
                self.last_average_rows,
                Path(REPORTS_DIR) / "average_wait_chart.png",
                "Найбільше середнє очікування за пунктами",
            )
        except RuntimeError as error:
            messagebox.showwarning("Потрібен matplotlib", str(error))
            return
        self.status_var.set(f"PNG збережено: {path}")
        messagebox.showinfo("Збережено", f"PNG-чарт збережено:\n{path}")

    def _average_report_text(self, rows: list[dict[str, object]], limit: int = 30) -> str:
        if not rows:
            return "Немає даних для таблиці середнього очікування."
        lines = ["Середній час очікування: пункт x день x місяць", ""]
        for row in rows[:limit]:
            lines.append(
                f"{row.get('month_name')} | {row.get('weekday_name')} | {row.get('crossing')} | "
                f"{format_hours(row.get('avg_wait_hours'))} | n={row.get('samples')}"
            )
        return "\n".join(lines)

    def _draw_empty_chart(self) -> None:
        self.chart_canvas.delete("all")
        self.chart_canvas.create_text(150, 190, text="Немає даних", fill="#60716d", font=("Segoe UI", 12, "bold"))

    def _draw_chart(self, rows: list[dict[str, object]]) -> None:
        self.chart_canvas.delete("all")
        if not rows:
            self._draw_empty_chart()
            return

        chart_rows = sorted(rows, key=lambda item: float(item.get("avg_wait_hours", 0)))[:9]
        width = max(self.chart_canvas.winfo_width(), 300)
        left_pad = 8
        label_width = 172
        bar_left = left_pad + label_width
        bar_max_width = max(80, width - bar_left - 34)
        row_height = 44
        top = 26
        max_value = max(float(row.get("avg_wait_hours", 0)) for row in chart_rows) or 1

        self.chart_canvas.create_text(left_pad, 10, text="Найшвидші пункти", anchor="w", fill="#183e38", font=("Segoe UI Semibold", 11))

        for index, row in enumerate(chart_rows):
            y = top + index * row_height
            crossing = str(row.get("crossing", ""))
            label = crossing[:29] + "..." if len(crossing) > 32 else crossing
            value = float(row.get("avg_wait_hours", 0))
            bar_width = int((value / max_value) * bar_max_width)
            color = "#1f6f5f" if index == 0 else "#73a89b"

            self.chart_canvas.create_text(left_pad, y + 11, text=label, anchor="w", fill="#24312e", font=("Segoe UI", 8))
            self.chart_canvas.create_rectangle(bar_left, y, bar_left + bar_width, y + 18, fill=color, outline="")
            self.chart_canvas.create_text(bar_left + bar_width + 5, y + 9, text=format_hours(value), anchor="w", fill="#24312e", font=("Segoe UI", 8))

    def _set_text(self, widget, content: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", END)
        widget.insert("1.0", content)
        widget.configure(state="disabled")

    def _clear_tree(self, tree: ttk.Treeview) -> None:
        for item in tree.get_children():
            tree.delete(item)


def main() -> None:
    app = BorderPlannerApp()
    app.mainloop()


if __name__ == "__main__":
    main()
