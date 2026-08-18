#!/usr/bin/python3
import tkinter as tk
from tkinter import messagebox
import paramiko
import os
import shutil
from datetime import datetime

# Импортируем базовый GUI из первой части (gui_elements.py)
from gui_elements import DiagnosticAppBase

class DiagnosticApp(DiagnosticAppBase):
    def start_diagnostic_thread(self):
        """Запуск логики без фоновых потоков во избежание SegFault"""
        if not all([self.entry_host.get(), self.entry_user.get(), self.entry_slot.get()]):
            messagebox.showwarning("Внимание", "Заполните обязательные поля: Хост, Пользователь и Слот!")
            return

        self.btn_run.configure(state="disabled")
        self.clear_log()
        self.root.update()

        try:
            self.run_diagnostic()
        except Exception as e:
            messagebox.showerror("Ошибка", f"Произошел программный сбой:\n{e}")
        finally:
            self.btn_run.configure(state="normal")
            self.root.update()

    def update_gui(self, text, tag="info"):
        """Печать строки и мгновенная перерисовка экрана"""
        self.log(text, tag)
        self.root.update()

    def swap_bytes_16(self, val_int):
        """Разворот байт для 16-битных систем (Big-Endian)"""
        return ((val_int & 0xFF) << 8) | ((val_int >> 8) & 0xFF)

    def swap_bytes_32(self, val_int):
        """Разворот байт для 32-битного слова (Dword) под Big-Endian"""
        return (
            ((val_int & 0x000000FF) << 24) |
            ((val_int & 0x0000FF00) << 8)  |
            ((val_int & 0x00FF0000) >> 8)  |
            ((val_int & 0xFF000000) >> 24)
        )

    def read_block_serial(self, client, slot):
        """Парсинг заводского номера и версии PCB из EEPROM 24LC014"""
        eeprom_addr = "0x50"
        cmd = f"for reg in $(seq 0 31); do h=$(i2cget -y {slot} {eeprom_addr} $reg b 2>/dev/null || echo '00'); echo -n \"${{h#0x}} \"; done"
        stdin, stdout, stderr = client.exec_command(cmd)

        raw_output = stdout.read().decode().strip()
        bytes_list = raw_output.split()

        if not bytes_list or len(bytes_list) < 32:
            return "UNKNOWN_SERIAL", "UNKNOWN_PCB"

        # Извлекаем заводской номер (строка 0x00, байты 8-15)
        serial_str = ""
        for b in bytes_list[8:16]:
            try:
                val = int(b, 16)
                if 33 <= val <= 126: serial_str += chr(val)
            except ValueError: continue
        serial_str = serial_str.strip() if serial_str else "UNKNOWN_SERIAL"

        # Извлекаем версию печатной платы PCB (строка 0x10, байты 4-11)
        pcb_str = ""
        for b in bytes_list[20:28]:
            try:
                val = int(b, 16)
                if 32 <= val <= 126: pcb_str += chr(val)
            except ValueError: continue
        pcb_str = pcb_str.strip() if pcb_str else "UNKNOWN_VERSION"

        return serial_str, pcb_str

    def run_diagnostic(self):
        host = self.entry_host.get()
        user = self.entry_user.get()
        password = self.entry_password.get()
        slot = self.entry_slot.get()

        i2caddr = 0x55
        STATUS_FAN = [0x71, 0x72, 0x73, 0x74, 0x75, 0x76, 0x77]
        STATUS_FAN_RPM = [0x50, 0x52, 0x54, 0x56, 0x58, 0x5a, 0x5c]
        UFM0_FAN_NUMBER = "0x8001"
        STATUS_POWER = "0x0031"
        ERRORS_MAP = {
            0: "Авария питания 12 Вольт - Только для МВ-2",
            1: "Авария первичного питания на шине A",
            2: "Авария первичного питания на шине B"
        }

        self.update_gui(f"=== Запуск проверки хоста {host} в {datetime.now().strftime('%H:%M:%S')} ===", "header")

        hosts_file = os.path.expanduser('~/.ssh/known_hosts')
        if os.path.exists(hosts_file):
            try:
                host_keys = paramiko.HostKeys(filename=hosts_file)
                if host_keys.lookup(host):
                    backup = f"{hosts_file}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.bak"
                    shutil.copy2(hosts_file, backup)
                    host_keys._entries = [e for e in host_keys._entries if not host_keys.check(host, e.key)]
                    host_keys.save(hosts_file)
                    self.update_gui("Старый SSH-ключ успешно удален из известного списка.")
                    if os.path.exists(backup): os.remove(backup)
            except Exception as e:
                self.update_gui(f"Предупреждение при очистке known_hosts: {e}", "warning")

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        try:
            self.update_gui(f"Установка SSH соединения с {host}...")
            client.connect(host, username=user, password=password, timeout=10)
        except Exception as e:
            self.update_gui(f"Критическая ошибка подключения: {e}", "error")
            return

        try:
            # 1. Вычитываем паспортные данные из EEPROM
            serial_number, pcb_version = self.read_block_serial(client, slot)
            log_filename = f"repair_history_{serial_number}.log"

            # 2. Читаем 32-битный регистр 0x0000 из ПЛИС (0x55)
            # Так как i2cget в некоторых системах не поддерживает тип 'i' (32-бит) напрямую,
            # мы читаем его как два слова 'w' подряд либо одной командой i2ctransfer (если она есть).
            # Самый надежный кроссплатформенный вариант - прочитать два word регистра и склеить их.
            self.update_gui("=== Вычитывание версии проекта из ПЛИС (0x55) ===", "warning")

            # Читаем старшее и младшее слово 32-битного регистра
            cmd_fpga = f"w1=$(i2cget -y {slot} {i2caddr} 0x0000 w 2>/dev/null || echo '0000'); echo $w1"
            stdin, stdout, stderr = client.exec_command(cmd_fpga)
            raw_fpga = stdout.read().decode().strip()
            clean_fpga = "".join(c for c in raw_fpga if c.isalnum())

            fpga_project_str = "UNKNOWN_PROJECT"
            if clean_fpga:
                try:
                    fpga_val = int(clean_fpga, 16)
                    # Применяем 32-битный разворот байт под Big-Endian архитектуру
                    fpga_val = self.swap_bytes_32(fpga_val)

                    # Предположим стандартную инженерную кодировку:
                    # Например, старшие 16 бит - Версия (Major.Minor), младшие 16 бит - Дата (Месяц.Год или День.Месяц)
                    # Либо это просто Hex-код, преобразуемый в ASCII. Выведем его в Hex и попробуем извлечь ASCII:
                    hex_32 = f"{fpga_val:08X}"

                    # Попытка декодировать в ASCII (если там зашит текст типа 'V1.0')
                    ascii_fpga = ""
                    for i in range(0, 8, 2):
                        part = int(hex_32[i:i+2], 16)
                        if 32 <= part <= 126: ascii_fpga += chr(part)

                    fpga_project_str = f"Hex: 0x{hex_32}"
                    if len(ascii_fpga) >= 2:
                        fpga_project_str += f" ({ascii_fpga})"
                except Exception:
                    pass

            # Выводим объединенный красивый паспорт в GUI
            self.update_gui(f"\n[ПАСПОРТ ОБОРУДОВАНИЯ]", "header")
            self.update_gui(f"-> Заводской номер блока: {serial_number}", "info")
            self.update_gui(f"-> Версия печатной платы: {pcb_version}", "info")
            self.update_gui(f"-> Версия проекта (ПЛИС): {fpga_project_str}", "info")
            self.update_gui("=" * 50 + "\n")

            # --- Контроль питания ---
            self.update_gui("Проверка датчиков электропитания...")
            stdin, stdout, stderr = client.exec_command(f"i2cget -y {slot} {i2caddr} {STATUS_POWER}w b")

            pwr_err = stderr.read().decode().strip()
            if pwr_err:
                self.update_gui(f"[Ошибка I2C / Слот {slot}]: {pwr_err}", "error")
                self.update_gui("-> Проверьте правильность указания номера слота (шины I2C)!", "warning")
                self.update_gui("-> Убедитесь, что оборудование инициализировано и ПЛИС доступна.", "warning")
                return

            raw_pwr = stdout.read().decode().strip()
            clean_pwr_str = "".join(c for c in raw_pwr if c.isalnum())
            if not clean_pwr_str:
                self.update_gui("Ошибка: Регистр питания вернул некорректные или пустые данные.", "error")
                return

            pwr_val = int(clean_pwr_str, 16)
            if pwr_val > 255: pwr_val = self.swap_bytes_16(pwr_val)

            if pwr_val == 0:
                self.update_gui("\n-> Аварий по первичному питанию не обнаружено --")
                self.update_gui("--------------------------------------------------")
            else:
                errors_found = False
                for bit, txt in ERRORS_MAP.items():
                    if (pwr_val & (1 << bit)) != 0:
                        self.update_gui(f"\n{txt}", "error")
                        errors_found = True
                if not errors_found:
                    self.update_gui(f"\nОбнаружена неизвестная авария (код регистра: {hex(pwr_val)})", "error")

            # --- Опрос вентиляторов ---
            self.update_gui("Запрос количества вентиляторов...")
            stdin, stdout, stderr = client.exec_command(f'i2cget -y {slot} {i2caddr} {UFM0_FAN_NUMBER}w b')

            fan_err = stderr.read().decode().strip()
            if fan_err:
                self.update_gui(f"[Ошибка чтения количества вентиляторов]: {fan_err}", "error")
                return

            raw_fn = stdout.read().decode().strip()
            clean_fn_str = ''.join(c for c in raw_fn if c.isalnum())
            if not clean_fn_str:
                self.update_gui("Ошибка: Не удалось прочитать количество вентиляторов (пустой ответ).", "error")
                return

            fan_num = int(clean_fn_str, 16)
            if fan_num > 255: fan_num = self.swap_bytes_16(fan_num)
            fan_num = min(fan_num, len(STATUS_FAN))
            self.update_gui(f"\n-> Начинаем проверку аварий по вентиляторам:", "header")

            for i in range(fan_num):
                self.update_gui(f"\nfan {i+1}", "header")
                stdin, stdout, stderr = client.exec_command(f'i2cget -y {slot} {i2caddr} {hex(STATUS_FAN[i])}w b')

                err_msg = stderr.read().decode().strip()
                if err_msg:
                    self.update_gui(f"Ошибка чтения статуса fan {i+1}: {err_msg}", "error")
                    continue

                raw_st = stdout.read().decode().strip()
                if not raw_st:
                    self.update_gui("Данные не получены", "warning")
                    continue

                clean_st_str = ''.join(c for c in raw_st if c.isalnum())
                if not clean_st_str: continue
                r_status = int(clean_st_str, 16)
                if r_status > 255: r_status = self.swap_bytes_16(r_status)

                if r_status == 0:
                    self.update_gui(f"\nfan {i+1}: OK")
                    self.update_gui("\nАварий по питанию и скорости вращения вентилятора не обнаружено")
                elif r_status == 1:
                    self.update_gui(f"\nfan {i+1}: АВАРИЯ ПО ПИТАНИЮ.", "error")
                    self.update_gui("-> Проверьте наличие напряжения питания на вентиляторе")
                    self.update_gui("-> Проверьте наличие установленных DNP элементов, при необходимости демонтируйте их")
                elif r_status in (2, 3):
                    if r_status == 2:
                        self.update_gui(f"\nfan {i+1}: АВАРИЯ СКОРОСТИ ВРАЩЕНИЯ ВЕНТИЛЯТОРА", "error")
                    else:
                        self.update_gui(f"\nfan {i+1}: АВАРИЯ ПО ПИТАНИЮ.", "error")
                        self.update_gui("\n-> Проверьте наличие напряжения питания вентилятора.")
                        self.update_gui("\n-> Проверьте наличие установленных DNP элементов, при необходимости демонтируйте их")
                        self.update_gui(f"\n-> FAN {i+1}: Авария скорости вращения вентилятора", "error")

                    self.update_gui("\n-> Дополнительная проверка оборотов вентилятора", "warning")

                    cmd_rpm = (
                        f"for step in $(seq 10000); do "
                        f"  val=$(i2cget -y {slot} {i2caddr} {STATUS_FAN_RPM[i]}w w 2>/dev/null || echo '0x0000'); "
                        f"  if [ \"$val\" = \"0x0000\" ] || [ \"$val\" = \"0x0\" ] || [ \"$val\" = \"0\" ]; then "
                        f"    echo 'ZERO'; break; "
                        f"  fi; "
                        f"done"
                    )
                    stdin, stdout, stderr = client.exec_command(cmd_rpm)
                    has_zero = any("ZERO" in line for line in stdout)

                    if not has_zero:
                        self.update_gui("\n-> Просадок оборотов до нуля нет")
                        self.update_gui("\n-> Проверьте напряжение питания вентилятора")
                        self.update_gui("\n-> Проверьте работоспособность цепей управления вентилятором и обратную связь с ПЛИС")
                        self.update_gui("\n-> Замените вентилятор на заведомо исправный, если ошибка уйдёт, то необходима замена вентилятора")
                        self.update_gui("\n-> Если проблема осталась - проверьте работоспособность ПЛИС, при необходимости замените")
                    else:
                        self.update_gui("АВАРИЯ ВЕНТИЛЯТОРА", "error")
                        self.update_gui("\n-> Проверьте работу вентилятора")
                        self.update_gui("\n-> Проверьте напряжение питания вентилятора")
                        self.update_gui("\n-> Проверьте цепи управления вентилятором")
                        self.update_gui("\n-> Убедитесь, что провода не пережаты, проверьте целостность проводов вентилятора.")
                        self.update_gui("\n-> Замените вентилятор на заведомо исправный, если ошибка уйдёт, то необходима замена вентилятора")
                else:
                    self.update_gui(f"\nfan {i+1}: Неизвестный код статуса ({hex(r_status)})", "error")
                    self.update_gui("\n-> Возможно вентилятор отсутствует или вы указали неправильный адрес оборудования", "warning")
                    self.update_gui("\n-> Возможно проблема с доступом к ПЛИС, проверьте цепи управления I2C и наличие питания на ПЛИС", "warning")

                loop_err = stderr.read().decode().strip()
                if loop_err: self.update_gui(f"\n[stderr]: {loop_err}", "error")
                self.update_gui('\n*****************')

            # --- Автоматическое логирование отчета ---
            try:
                full_log_content = self.txt_log.get("1.0", tk.END)
                with open(log_filename, "a", encoding="utf-8") as f:
                    f.write(f"\n\n{'='*60}\n")
                    f.write(f"ДАТА ПРОВЕРКИ ОБОРУДОВАНИЯ: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                    f.write(f"{'='*60}\n")
                    f.write(full_log_content)
                self.update_gui(f"\n[СИСТЕМА]: Данные внесены в журнал ремонтов блока: {log_filename}", "info")
            except Exception as file_err:
                self.update_gui(f"\n[ОШИБКА ЖУРНАЛА]: Не удалось записать лог на диск: {file_err}", "error")

        finally:
            client.close()
            self.update_gui("\n=== Проверка завершена. SSH-сессия закрыта. ===", "header")

if __name__ == "__main__":
    root = tk.Tk()
    app = DiagnosticApp(root)
    root.mainloop()
