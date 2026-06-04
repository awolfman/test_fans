#!/usr/bin/python3

# Формат команды: ./script.py <host> <user> '' <slot>"

# Данный скрипт написан под Big-Eendian архитектуру.
# Для Little-Endian необходимо сделать переворот данных при работе по I2C

import paramiko
import socket
import sys
import time
import os
import shutil
from datetime import datetime

# Проверка аргументов командной строки
if len(sys.argv) < 5:
    print("\nИспользование: script.py <host> <user> <password> <slot>")
    sys.exit(1)

host = sys.argv[1]
user = sys.argv[2]
password = sys.argv[3]
slot = sys.argv[4]

# Проверка наличия и удаления ssh-ключа конкретного хоста с бэкапом и поддержкой хеширования

# Пути к файлам
hosts_file = os.path.expanduser('~/.ssh/known_hosts')
backup_file = f"{hosts_file}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.bak"

# Загружаем текущие ключи
if not os.path.exists(hosts_file):
    print(f"Ошибка: файл {hosts_file} не найден.", file=sys.stderr)
    sys.exit(1)

host_keys = paramiko.HostKeys(filename=hosts_file)

# Ищем записи, соответствующие хосту (включая хэшированные)
matched_entries = host_keys.lookup(host)

if matched_entries:
    # Создаем временный бэкап перед изменениями
    try:
        shutil.copy2(hosts_file, backup_file)
        print(f"Создан временный бэкап: {backup_file}")
    except Exception as e:
        print(f"Критическая ошибка: не удалось создать бэкап. Изменения не внесены. {e}", file=sys.stderr)
        sys.exit(1)

    # Фильтруем записи, удаляя те, которые соответствуют нашему хосту
    keys_to_remove = list(matched_entries.keys())
    host_keys._entries = [
        entry for entry in host_keys._entries 
        if not (host_keys.check(host, entry.key) and entry.key.get_name() in keys_to_remove)
    ]

    # Безопасное сохранение изменений и удаление бэкапа
    try:
        # Пытаемся сохранить файл
        host_keys.save(hosts_file)
        print(f"Ключи для хоста {host} успешно удалены из {hosts_file}")
        
        # Если сохранение прошло успешно — удаляем бэкап
        if os.path.exists(backup_file):
            os.remove(backup_file)
            print("Временный бэкап успешно удален.")
            
    except PermissionError:
        print(f"Ошибка доступа: нет прав на запись в файл {hosts_file}. Бэкап сохранен в {backup_file}", file=sys.stderr)
    except Exception as e:
        print(f"Не удалось сохранить файл {hosts_file}. Ошибка: {e}. Бэкап сохранен в {backup_file}", file=sys.stderr)
else:
    print(f"Хост {host} не найден в {hosts_file} (проверены явные и хэшированные записи)")

# I2C address
i2caddr = 0x55

# Регистры
STATUS_FAN = [0x71, 0x72, 0x73, 0x74, 0x75, 0x76, 0x77]
STATUS_FAN_RPM = [0x50, 0x52, 0x54, 0x56, 0x58, 0x5a, 0x5c]
UFM0_FAN_NUMBER = "0x8001"
STATUS_POWER = "0x0031"

# Словарь масок: ключ - сдвиг бита, значение - описание аварии
ERRORS_MAP = {
    0: "Авария питания 12 Вольт - Только для МВ-2",
    1: "Авария первичного питания на шине A",
    2: "Авария первичного питания на шине B"
}

client = paramiko.SSHClient()
client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

try:
    client.connect(host, username=user, password=password)
except (socket.gaierror, socket.error, socket.timeout, TimeoutError, IOError, paramiko.SSHException) as e:
    print(f"Не удалось подключиться к {host}. Ошибка: {e}")
    sys.exit(1)

try:
    # Проверяем состояние датчиков контроля электропитания
    command_staus_power = f"i2cget -y {slot} {i2caddr} {STATUS_POWER}w b"
    (stdin, stdout, stderr) = client.exec_command(command_staus_power)
    
    # Проверка системных ошибок выполнения (SSH)
    error_msg = stderr.read().decode().strip()
    if error_msg:
        print(f"Ошибка выполнения команды: {error_msg}")
        sys.exit(1)
    
    # Чтение и очистка вывода i2cget
    raw_status_power = stdout.read().decode().strip()
    clean_hex = "".join(char for char in raw_status_power if char.isalnum())
    
    if not clean_hex:
        print("Ошибка: Получены пустые данные от устройства.")
        sys.exit(1)
    
    try:
        # Конвертируем очищенную строку (например, '0x03' или '3') в int
        status_powers = int(clean_hex, 16)
    except ValueError:
        print(f"Ошибка: Не удалось распознать шестнадцатеричное число: {clean_hex}")
        sys.exit(1)
    
    # Анализ состояния регистра питания
    if status_powers == 0:
        print("\n-> Аварий по первичному питанию не обнаружено --")
        print("--------------------------------------------------")
    else:
        errors_found = False
        
        # Проверяем каждый бит из нашей карты ошибок
        for bit_offset, error_text in ERRORS_MAP.items():
            # Побитовое И с маской (1, 2, 4, 8 и т.д.)
            if (status_powers & (1 << bit_offset)) != 0:
                print(f"\n{error_text}")
                errors_found = True
                
        # Если регистр не 0, но известные нам биты не взведены
        if not errors_found:
            print(f"\nОбнаружена неизвестная авария (код регистра: {hex(status_powers)})")
    
    # Получаем кол-во вентиляторов в Модуле вентиляторов
    cmd = f'i2cget -y {slot} {i2caddr} {UFM0_FAN_NUMBER}w b'
    (stdin, stdout, stderr) = client.exec_command(cmd)    
    error_msg = stderr.read().decode().strip()
    
    if error_msg:
        print(f"Ошибка выполнения команды: {error_msg}")
        sys.exit(1)

    raw_fan_number = stdout.read().decode().strip()
    fan_number = int(''.join(char for char in raw_fan_number if char.isalnum()) , 16)
    
    # Ограничиваем количество вентиляторов размером массива регистров
    fan_number = min(fan_number, len(STATUS_FAN))
    print (f"\n-> Начинаем проверку аварий по вентиляторам:")

    for i in range(fan_number):
        print(f"\nfan {i+1}")

        # Проверка статуса аварий
        cmd_status = f'i2cget -y {slot} {i2caddr} {hex(STATUS_FAN[i])}w b'
        (stdin, stdout, stderr) = client.exec_command(cmd_status)
        
        err_msg = stderr.read().decode().strip()
        if err_msg:
            print(f"Ошибка чтения статуса fan {i+1}: {err_msg}")
            continue

        raw_status_fan = stdout.read().decode()
        if not raw_status_fan:
            print("Данные не получены")
            continue
            
        r_status_fan = int(''.join(char for char in raw_status_fan if char.isalnum()) , 16)
        
        if r_status_fan == 0 :
            print(f"\nfan {i+1}: OK")
            print (f"\nАварий по питанию и скорости вращения вентилятора не обнаружено")

        elif r_status_fan == 1 :
            print(f"\nfan {i+1}: АВАРИЯ ПО ПИТАНИЮ.")
            print ("-> Проверьте наличие напряжения питания на вентиляторе")
            print ("-> Проверьте наличие установленных DNP элементов, при необходимости демонтируйте их")
            
        elif r_status_fan == 2 :
            print(f"\nfan {i+1}: АВАРИЯ СКОРОСТИ ВРАЩЕНИЯ ВЕНТИЛЯТОРА")
            
            # Проверка аварий по оборотам
            print("\n-> Дополнительная проверка оборотов вентилятора")
            
            cmd = f"for step in $(seq 10000); do i2cget -y {slot} {i2caddr} {STATUS_FAN_RPM[(i)]}w w || echo '0x0000'; done"
            stdin, stdout, stderr = client.exec_command(cmd)
            remote_errors = stderr.read().decode('utf-8').strip()
            
            # Проверяем критические ошибки SSH/Bash
            if remote_errors and not stdout.channel.recv_ready():
                print(f"Критическая ошибка выполнения: {remote_errors}")
                sys.exit(1)

             # Читаем и анализируем вывод построчно без создания файлов
            has_zero_rpm = False

            for line in stdout:
                val = line.strip()                
                # Сравниваем строковые значения, так как i2cget и echo возвращают текст
                if val in ("0x0000", "0", "0x0"):
                    has_zero_rpm = True
                    break  # Нашли хотя бы одну просадку, можно не продолжать
                    
            # Логика вывода результатов
            if not has_zero_rpm:
                print("\n-> Просадок оборотов до нуля нет")
                print("\n-> Проверьте напряжение питания вентилятора")
                print("\n-> Проверьте работоспособность цепей управления вентилятором и обратную связь с ПЛИС")
                print("\n-> Замените вентилятор на заведомо исправный, если ошибка уйдёт, то необходима замена вентилятора")
                print("\n-> Если проблема осталась - проверьте работоспособность ПЛИС, при необходимости замените")
            else:
                print("\n-> Проблема с вентилятором: обнаружена просадка оборотов до нуля!")
                print("\n-> Проверьте работу вентилятора")
                print("\n-> Проверьте напряжение питания вентилятора")
                print("\n-> Проверьте цепи управления вентилятором")
                print("\n-> Убедитесь, что провода не пережаты, проверьте целостность проводов вентилятора.")
                print("\n-> Замените вентилятор на заведомо исправный, если ошибка уйдёт, то необходима замена вентилятора")

        elif r_status_fan == 3:
            print (f"\nfan {i+1}: АВАРИЯ ПО ПИТАНИЮ.")
            print (f"\n-> Проверьте наличие напряжения питания вентилятора.")
            print ("\n-> Проверьте наличие установленных DNP элементов, при необходимости демонтируйте их")
            print (f"\n-> FAN {i+1}: Авария скорости вращения вентилятора" )
            
            # Проверка аварий по оборотам
            cmd = f"for step in $(seq 10000); do i2cget -y {slot} {i2caddr} {STATUS_FAN_RPM[(i)]}w w || echo '0x0000'; done"
            stdin, stdout, stderr = client.exec_command(cmd)
            remote_errors = stderr.read().decode('utf-8').strip()
            
            # Проверяем критические ошибки SSH/Bash
            if remote_errors:
                print(f"Критическая ошибка выполнения: {remote_errors}")
                sys.exit(1)
                
             # Читаем и анализируем вывод построчно без создания файлов
            has_zero_rpm = False
            for line in stdout:
                val = line.strip()
                # Проверяем просадку до нуля (в шестнадцатеричном или десятичном формате)
                if val == "0x0000" or val == "0" or val == "0x0":
                    has_zero_rpm = True
                    break  # Нашли хотя бы одну просадку, можно не продолжать
                    
            # Логика вывода результатов
            if not has_zero_rpm:
                    print (f"\n-> Просадок оборотов до нуля нет")
                    print (f"\n-> Проверьте напряжение питания вентилятора")
                    print (f"\n-> Проверьте работоспособность цепей управления вентилятором и обратную связь с ПЛИС")
                    print (f"\n-> Замените вентилятор на заведомо исправный, если ошибка уйдёт, то необходима замена вентилятора")
                    print (f"\n-> Если проблема осталась - проверьте работоспособность ПЛИС, при необходимости замените")                    
            else:
                # Если в output что-то есть, значит совпадения найдены
                print ("АВАРИЯ ВЕНТИЛЯТОРА")                
                print (f"\n-> Проверьте работу вентилятора")
                print (f"\n-> Проверьте напряжение питания вентилятора")
                print (f"\n-> Проверьте цепи управления вентилятором")
                print (f"\n-> Убедитесь, что провода не пережаты, проверьте целостность проводов вентилятора.")
                print (f"\n-> Замените вентилятор на заведомо исправный, если ошибка уйдёт, то необходима замена вентилятора")
                
        else:
            print(f"\nfan {i+1}: Неизвестный код статуса ({hex(r_status_fan)})")
            print ("\n-> Возможно вентилятор отсутствует или вы указали неправильный адрес оборудования")
            print ("\n-> Возможно проблема с доступом к ПЛИС, проверьте цепи управления I2C и наличие питания на ПЛИС")
            
        #
        for line in stderr:
            print (line)
            sys.exit(1)
        print ('\n*****************')

finally:
    client.close()
