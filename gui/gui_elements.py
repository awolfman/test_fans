import tkinter as tk
from tkinter import ttk, scrolledtext

class DiagnosticAppBase:
    def __init__(self, root):
        self.root = root
        self.root.title("Диагностика оборудования (I2C/PMBus)")
        self.root.geometry("750x650")
        self.root.minsize(600, 500)

        self.style = ttk.Style()
        self.style.theme_use("clam")
        self.create_widgets()

    def create_widgets(self):
        input_frame = ttk.LabelFrame(self.root, text=" Параметры подключения SSH & I2C ", padding=10)
        input_frame.pack(fill="x", padx=15, pady=10)

        ttk.Label(input_frame, text="Хост (IP):").grid(row=0, column=0, sticky="w", padx=5, pady=5)
        self.entry_host = ttk.Entry(input_frame, width=20)
        self.entry_host.insert(0, "192.168.1.100")
        self.entry_host.grid(row=0, column=1, padx=5, pady=5)

        ttk.Label(input_frame, text="Слот (I2C Bus):").grid(row=0, column=2, sticky="w", padx=15, pady=5)
        self.entry_slot = ttk.Entry(input_frame, width=10)
        self.entry_slot.insert(0, "1")
        self.entry_slot.grid(row=0, column=3, padx=5, pady=5)

        ttk.Label(input_frame, text="Пользователь:").grid(row=1, column=0, sticky="w", padx=5, pady=5)
        self.entry_user = ttk.Entry(input_frame, width=20)
        self.entry_user.insert(0, "root")
        self.entry_user.grid(row=1, column=1, padx=5, pady=5)

        ttk.Label(input_frame, text="Пароль:").grid(row=1, column=2, sticky="w", padx=15, pady=5)
        self.entry_password = ttk.Entry(input_frame, width=20, show="*")
        self.entry_password.grid(row=1, column=3, padx=5, pady=5)

        # Кнопка запуска
        self.btn_run = ttk.Button(input_frame, text="Запустить проверку", command=self.start_diagnostic_thread)
        self.btn_run.grid(row=0, column=4, padx=20, pady=5, sticky="ew")

        # КНОПКА ВЫХОД (закрывает окно приложения)
        self.btn_exit = ttk.Button(input_frame, text="Выход", command=self.root.destroy)
        self.btn_exit.grid(row=1, column=4, padx=20, pady=5, sticky="ew")

        log_frame = ttk.LabelFrame(self.root, text=" Ход выполнения и результаты ", padding=10)
        log_frame.pack(fill="both", expand=True, padx=15, pady=10)

        self.txt_log = scrolledtext.ScrolledText(
            log_frame, wrap=tk.WORD, font=("Courier New", 10),
            background="#1e1e1e", foreground="#ffffff"
        )
        self.txt_log.pack(fill="both", expand=True)

        self.txt_log.tag_config("info", foreground="#00FF00")
        self.txt_log.tag_config("error", foreground="#FF5555")
        self.txt_log.tag_config("warning", foreground="#FFFF55")
        self.txt_log.tag_config("header", foreground="#55FFFF")

    def log(self, text, tag="info"):
        self.txt_log.configure(state='normal')
        self.txt_log.insert(tk.END, text + "\n", tag)
        self.txt_log.configure(state='disabled')
        self.txt_log.see(tk.END)

    def clear_log(self):
        self.txt_log.configure(state='normal')
        self.txt_log.delete('1.0', tk.END)
        self.txt_log.configure(state='disabled')

    def start_diagnostic_thread(self):
        pass
