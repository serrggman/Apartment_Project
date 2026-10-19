import hashlib
import hmac
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP

APP_NAME = "BuildFirm"
APP_VERSION = "1.0.0-beta.1"
BUILD_NUMBER = "2026.05.18-001"
AUTHOR = "Капранчук Сергій Сергійович"
GROUP = "580-ІПЗ"

DB_FILE = "buildfirm.db"
REPORTS_DIR = "reports"

SALT_BYTES = 16
HASH_ITERATIONS = 120_000
LOW_STOCK_DEFAULT = 10.0
BAR_WIDTH = 40
LINE_WIDTH = 80
DEFAULT_CURRENCY = "UAH"
LABEL_WIDTH = 20

ROLE_ADMIN = "admin"
ROLE_MANAGER = "manager"
ROLE_CLIENT = "client"

APARTMENT_STATUSES = ("available", "reserved", "sold")
STATUS_LABELS = {
    "available": "вільна",
    "reserved": "зарезервована",
    "sold": "продана",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS roles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS clients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name TEXT NOT NULL,
    phone TEXT,
    email TEXT
);
CREATE TABLE IF NOT EXISTS construction_objects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    address TEXT
);
CREATE TABLE IF NOT EXISTS suppliers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    phone TEXT
);
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    login TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    salt TEXT NOT NULL,
    role_code TEXT NOT NULL,
    client_id INTEGER REFERENCES clients(id),
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS apartments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    object_id INTEGER NOT NULL REFERENCES construction_objects(id),
    number TEXT NOT NULL,
    area REAL NOT NULL,
    rooms INTEGER NOT NULL,
    price REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'available'
);
CREATE TABLE IF NOT EXISTS materials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    unit TEXT NOT NULL,
    quantity REAL NOT NULL DEFAULT 0,
    price REAL NOT NULL DEFAULT 0,
    supplier_id INTEGER REFERENCES suppliers(id)
);
CREATE TABLE IF NOT EXISTS sales (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    apartment_id INTEGER NOT NULL REFERENCES apartments(id),
    client_id INTEGER NOT NULL REFERENCES clients(id),
    price REAL NOT NULL,
    sale_date TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS system_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_login TEXT,
    action TEXT NOT NULL,
    entity TEXT,
    entity_id INTEGER,
    details TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
CREATE TRIGGER IF NOT EXISTS trg_sale_marks_sold
AFTER INSERT ON sales
BEGIN
    UPDATE apartments SET status = 'sold' WHERE id = NEW.apartment_id;
END;
"""


def hash_password(password, salt=None):
    """Повертає (hex-hash, hex-salt) для пароля."""
    salt = salt or os.urandom(SALT_BYTES).hex()
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"),
        bytes.fromhex(salt), HASH_ITERATIONS,
    )
    return digest.hex(), salt


def verify_password(password, password_hash, salt):
    """Перевіряє пароль за збереженим хешем."""
    digest, _ = hash_password(password, salt)
    return hmac.compare_digest(digest, password_hash)


def get_conn():
    """Відкриває з'єднання з БД із увімкненими зовнішніми ключами."""
    conn = sqlite3.connect(DB_FILE)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Створює схему (якщо потрібно) та заповнює тестовими даними."""
    conn = get_conn()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
        seed_data(conn)
    finally:
        conn.close()


def seed_data(conn):
    """Заповнює БД тестовими даними лише при першому запуску."""
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM users")
    if cur.fetchone()[0] > 0:
        return
    for code, name in [
        (ROLE_ADMIN, "Адміністратор"),
        (ROLE_MANAGER, "Менеджер"),
        (ROLE_CLIENT, "Клієнт"),
    ]:
        cur.execute("INSERT INTO roles(code, name) VALUES (?, ?)", (code, name))
    for name, phone in [
        ("Будматеріали Плюс", "+380441234567"),
        ("ЦементБетон", "+380442345678"),
        ("Електротовари Київ", "+380443456789"),
    ]:
        cur.execute("INSERT INTO suppliers(name, phone) VALUES (?, ?)", (name, phone))
    for name, addr in [
        ("ЖК Сонячний", "м. Київ, вул. Сонячна 15"),
        ("ЖК Лісовий", "м. Київ, вул. Лісова 42"),
    ]:
        cur.execute(
            "INSERT INTO construction_objects(name, address) VALUES (?, ?)",
            (name, addr),
        )
    for row in [
        (1, "101", 65.5, 2, 1850000.00, "available"),
        (1, "102", 85.0, 3, 2400000.00, "available"),
        (1, "103", 45.0, 1, 1300000.00, "reserved"),
        (1, "104", 75.0, 3, 2100000.00, "sold"),
        (2, "201", 72.0, 2, 2000000.00, "available"),
        (2, "202", 110.0, 4, 3200000.00, "available"),
        (2, "203", 55.0, 2, 1550000.00, "sold"),
        (2, "204", 60.0, 2, 1700000.00, "sold"),
    ]:
        cur.execute(
            "INSERT INTO apartments(object_id, number, area, rooms, price, status) "
            "VALUES (?, ?, ?, ?, ?, ?)", row,
        )
    for row in [
        ("Цемент М400", "кг", 1500.0, 4.50, 1),
        ("Цегла червона", "шт", 8000.0, 8.20, 1),
        ("Пісок", "т", 25.5, 850.00, 2),
        ("Арматура 12мм", "м", 500.0, 42.00, 2),
        ("Кабель ВВГ 3х2.5", "м", 300.0, 38.50, 3),
        ("Провід ПВ-1", "м", 50.0, 12.00, 3),
    ]:
        cur.execute(
            "INSERT INTO materials(name, unit, quantity, price, supplier_id) "
            "VALUES (?, ?, ?, ?, ?)", row,
        )
    cur.execute(
        "INSERT INTO clients(full_name, phone, email) VALUES (?, ?, ?)",
        ("Іванов Іван Іванович", "+380501112233", "ivanov@example.com"),
    )
    cur.execute(
        "INSERT INTO clients(full_name, phone, email) VALUES (?, ?, ?)",
        ("Петренко Олена Олексіївна", "+380502223344", "petrenko@example.com"),
    )
    for row in [
        (4, 1, 2100000.00, "2026-02-20"),
        (7, 2, 1550000.00, "2026-04-15"),
        (8, 1, 1700000.00, "2026-05-10"),
    ]:
        cur.execute(
            "INSERT INTO sales(apartment_id, client_id, price, sale_date) "
            "VALUES (?, ?, ?, ?)", row,
        )
    for login, password, role, client_id in [
        ("admin", "admin123", ROLE_ADMIN, None),
        ("manager", "manager123", ROLE_MANAGER, None),
    ]:
        pwd_hash, salt = hash_password(password)
        cur.execute(
            "INSERT INTO users(login, password_hash, salt, role_code, client_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (login, pwd_hash, salt, role, client_id),
        )
    cur.execute(
        "INSERT INTO settings(key, value) VALUES (?, ?)",
        ("low_stock_threshold", str(LOW_STOCK_DEFAULT)),
    )
    cur.execute(
        "INSERT INTO settings(key, value) VALUES (?, ?)",
        ("currency", DEFAULT_CURRENCY),
    )
    conn.commit()


def get_setting(conn, key, default=None):
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(conn, key, value):
    conn.execute(
        "INSERT INTO settings(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, str(value)),
    )
    conn.commit()


def log_action(conn, user_login, action, entity=None, entity_id=None, details=None):
    """Записує дію користувача в журнал системи."""
    conn.execute(
        "INSERT INTO system_log(user_login, action, entity, entity_id, details) "
        "VALUES (?, ?, ?, ?, ?)",
        (user_login, action, entity, entity_id, details),
    )
    conn.commit()


def clear():
    os.system("cls" if os.name == "nt" else "clear")


def line(char="─", width=LINE_WIDTH):
    return char * width


def header(title):
    print()
    print(line())
    print(f"  {title}")
    print(line())


def prompt(text, default=None):
    suffix = f" [{default}]" if default is not None else ""
    val = input(f"{text}{suffix}: ").strip()
    return val if val else default


def prompt_int(text, default=None):
    while True:
        raw = prompt(text, default)
        try:
            return int(raw)
        except (TypeError, ValueError):
            print("  ! Введіть ціле число.")


def prompt_float(text, default=None):
    while True:
        raw = prompt(text, default)
        try:
            return float(raw)
        except (TypeError, ValueError):
            print("  ! Введіть число.")


def confirm(text="Підтвердити"):
    return prompt(f"{text} (y/n)", "n").lower().startswith("y")


def fmt_money(value):
    """Форматує суму з розділювачами тисяч."""
    try:
        d = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return f"{d:,.2f}".replace(",", " ").replace(".", ",")
    except (TypeError, ValueError):
        return str(value)


def render_table(headers, rows, widths=None):
    """Повертає відформатовану текстову таблицю."""
    if not rows:
        return "(порожньо)"
    if widths is None:
        widths = []
        for i, h in enumerate(headers):
            w = len(str(h))
            for r in rows:
                w = max(w, len(str(r[i])))
            widths.append(min(w, 40))
    sep = "+" + "+".join("-" * (w + 2) for w in widths) + "+"
    out = [sep]
    out.append("|" + "|".join(
        f" {str(h)[:widths[i]].ljust(widths[i])} " for i, h in enumerate(headers)
    ) + "|")
    out.append(sep)
    for row in rows:
        out.append("|" + "|".join(
            f" {str(c)[:widths[i]].ljust(widths[i])} " for i, c in enumerate(row)
        ) + "|")
    out.append(sep)
    return "\n".join(out)


def print_table(headers, rows, widths=None):
    print(render_table(headers, rows, widths))


def print_bar(label, value, max_value, width=BAR_WIDTH):
    """Друкує горизонтальну ASCII-смужку."""
    bar_len = 0 if max_value <= 0 else int(round(value / max_value * width))
    print(f"  {label[:LABEL_WIDTH].ljust(LABEL_WIDTH)} | "
          f"{'█' * bar_len}{' ' * (width - bar_len)} {value}")


def save_report(name, content):
    """Зберігає звіт у файл для друку."""
    os.makedirs(REPORTS_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(REPORTS_DIR, f"{name}_{ts}.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"  ✓ Збережено: {path}")


def list_apartments(conn, status=None, q=None, sort="id"):
    sql = (
        "SELECT a.id, a.number, a.area, a.rooms, a.price, a.status, "
        "o.name AS object_name FROM apartments a "
        "LEFT JOIN construction_objects o ON o.id = a.object_id WHERE 1=1 "
    )
    params = []
    if status:
        sql += "AND a.status = ? "
        params.append(status)
    if q:
        sql += "AND (a.number LIKE ? OR o.name LIKE ?) "
        params.extend([f"%{q}%", f"%{q}%"])
    if sort not in {"id", "number", "area", "price", "rooms"}:
        sort = "id"
    sql += f"ORDER BY a.{sort}"
    return conn.execute(sql, params).fetchall()


def get_apartment(conn, apartment_id):
    return conn.execute("SELECT * FROM apartments WHERE id = ?", (apartment_id,)).fetchone()


def add_apartment(conn, user_login, object_id, number, area, rooms, price):
    cur = conn.execute(
        "INSERT INTO apartments(object_id, number, area, rooms, price, status) "
        "VALUES (?, ?, ?, ?, ?, 'available')",
        (object_id, number, area, rooms, price),
    )
    log_action(conn, user_login, "INSERT", "apartments", cur.lastrowid, f"номер={number}")
    conn.commit()
    return cur.lastrowid


def update_apartment(conn, user_login, apartment_id, **fields):
    if not fields:
        return
    sets = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(
        f"UPDATE apartments SET {sets} WHERE id = ?",
        (*fields.values(), apartment_id),
    )
    log_action(conn, user_login, "UPDATE", "apartments", apartment_id,
               ",".join(f"{k}={v}" for k, v in fields.items()))
    conn.commit()


def delete_apartment(conn, user_login, apartment_id):
    conn.execute("DELETE FROM apartments WHERE id = ?", (apartment_id,))
    log_action(conn, user_login, "DELETE", "apartments", apartment_id)
    conn.commit()


def list_materials(conn, q=None):
    sql = (
        "SELECT m.id, m.name, m.unit, m.quantity, m.price, "
        "s.name AS supplier FROM materials m "
        "LEFT JOIN suppliers s ON s.id = m.supplier_id WHERE 1=1 "
    )
    params = []
    if q:
        sql += "AND m.name LIKE ? "
        params.append(f"%{q}%")
    sql += "ORDER BY m.name"
    return conn.execute(sql, params).fetchall()


def add_material(conn, user_login, name, unit, quantity, price, supplier_id=None):
    cur = conn.execute(
        "INSERT INTO materials(name, unit, quantity, price, supplier_id) "
        "VALUES (?, ?, ?, ?, ?)",
        (name, unit, quantity, price, supplier_id),
    )
    log_action(conn, user_login, "INSERT", "materials", cur.lastrowid, f"назва={name}")
    conn.commit()
    return cur.lastrowid


def update_material_quantity(conn, user_login, material_id, delta):
    conn.execute(
        "UPDATE materials SET quantity = quantity + ? WHERE id = ?",
        (delta, material_id),
    )
    log_action(conn, user_login, "UPDATE", "materials", material_id,
               f"зміна кількості на {delta}")
    conn.commit()


def low_stock_materials(conn, threshold=None):
    if threshold is None:
        threshold = float(get_setting(conn, "low_stock_threshold", LOW_STOCK_DEFAULT))
    return conn.execute(
        "SELECT id, name, unit, quantity FROM materials "
        "WHERE quantity < ? ORDER BY quantity", (threshold,),
    ).fetchall()


def list_clients(conn, q=None):
    sql = "SELECT id, full_name, phone, email FROM clients WHERE 1=1 "
    params = []
    if q:
        sql += "AND full_name LIKE ? "
        params.append(f"%{q}%")
    sql += "ORDER BY full_name"
    return conn.execute(sql, params).fetchall()


def add_client(conn, user_login, full_name, phone, email):
    cur = conn.execute(
        "INSERT INTO clients(full_name, phone, email) VALUES (?, ?, ?)",
        (full_name, phone, email),
    )
    log_action(conn, user_login, "INSERT", "clients", cur.lastrowid, full_name)
    conn.commit()
    return cur.lastrowid


def register_sale(conn, user_login, apartment_id, client_id):
    """Оформлює продаж. Статус квартири оновлюється тригером БД."""
    apt = get_apartment(conn, apartment_id)
    if apt is None:
        raise ValueError("Квартири з таким ID немає")
    if apt["status"] == "sold":
        raise ValueError("Квартира вже продана")
    price = apt["price"]
    today = date.today().isoformat()
    conn.execute(
        "INSERT INTO sales(apartment_id, client_id, price, sale_date) VALUES (?, ?, ?, ?)",
        (apartment_id, client_id, price, today),
    )
    log_action(conn, user_login, "SALE", "sales", apartment_id,
               f"client_id={client_id}, price={price}")
    conn.commit()


def list_sales(conn):
    return conn.execute(
        "SELECT s.id, s.sale_date, s.price, a.number AS apt_number, "
        "c.full_name AS client_name FROM sales s "
        "JOIN apartments a ON a.id = s.apartment_id "
        "JOIN clients c ON c.id = s.client_id "
        "ORDER BY s.sale_date DESC"
    ).fetchall()


def client_sales(conn, client_id):
    return conn.execute(
        "SELECT s.id, s.sale_date, s.price, a.number AS apt_number "
        "FROM sales s JOIN apartments a ON a.id = s.apartment_id "
        "WHERE s.client_id = ? ORDER BY s.sale_date DESC", (client_id,),
    ).fetchall()


def find_user(conn, login):
    return conn.execute(
        "SELECT * FROM users WHERE login = ? AND is_active = 1", (login,),
    ).fetchone()


def list_users(conn):
    return conn.execute(
        "SELECT id, login, role_code, is_active, created_at FROM users ORDER BY id"
    ).fetchall()


def create_user(conn, admin_login, login, password, role_code, client_id=None):
    pwd_hash, salt = hash_password(password)
    cur = conn.execute(
        "INSERT INTO users(login, password_hash, salt, role_code, client_id) "
        "VALUES (?, ?, ?, ?, ?)",
        (login, pwd_hash, salt, role_code, client_id),
    )
    log_action(conn, admin_login, "INSERT", "users", cur.lastrowid, f"login={login}")
    conn.commit()
    return cur.lastrowid


def toggle_user_active(conn, admin_login, user_id):
    conn.execute("UPDATE users SET is_active = 1 - is_active WHERE id = ?", (user_id,))
    log_action(conn, admin_login, "TOGGLE", "users", user_id)
    conn.commit()


def login_screen():
    header(f"{APP_NAME} {APP_VERSION}")
    print("  1. Вхід за логіном і паролем")
    print("  2. Увійти як гість (без пароля)")
    choice = prompt("Вибір", "1")
    if choice == "2":
        conn = get_conn()
        try:
            log_action(conn, "guest", "LOGIN")
        finally:
            conn.close()
        return {"login": "guest", "role_code": ROLE_CLIENT, "client_id": None}
    for _ in range(3):
        login = prompt("Логін")
        password = prompt("Пароль")
        conn = get_conn()
        try:
            user = find_user(conn, login)
            if user and verify_password(password, user["password_hash"], user["salt"]):
                log_action(conn, user["login"], "LOGIN")
                return dict(user)
            print("  ✗ Невірний логін або пароль.")
        finally:
            conn.close()
    print("Перевищено кількість спроб. Вихід.")
    return None


def show_apartments(conn, **kw):
    rows = list_apartments(conn, **kw)
    data = [
        (r["id"], r["number"], r["object_name"] or "—",
         f'{r["area"]:.1f}', r["rooms"],
         fmt_money(r["price"]), STATUS_LABELS.get(r["status"], r["status"]))
        for r in rows
    ]
    print_table(["ID", "Номер", "Об'єкт", "Площа", "Кімн.", "Ціна", "Статус"], data)


def add_apartment_ui(conn, user):
    objects = conn.execute("SELECT id, name FROM construction_objects ORDER BY name").fetchall()
    if not objects:
        print("  ! Спочатку створіть об'єкт будівництва")
        return
    print("Об'єкти:")
    for o in objects:
        print(f"  {o['id']}. {o['name']}")
    obj_id = prompt_int("ID об'єкта")
    number = prompt("Номер квартири")
    area = prompt_float("Площа (м²)")
    rooms = prompt_int("Кількість кімнат")
    price = prompt_float("Ціна")
    try:
        aid = add_apartment(conn, user["login"], obj_id, number, area, rooms, price)
        print(f"  ✓ Додано квартиру ID={aid}")
    except sqlite3.Error as exc:
        print(f"  ! Помилка: {exc}")


def edit_apartment_ui(conn, user):
    aid = prompt_int("ID квартири для редагування")
    apt = get_apartment(conn, aid)
    if not apt:
        print("  ! Квартиру не знайдено")
        return
    print(f"  Поточна ціна: {fmt_money(apt['price'])}; статус: {apt['status']}")
    new_price = prompt_float("Нова ціна (Enter — залишити)", apt["price"])
    new_status = prompt(
        f"Новий статус {'/'.join(APARTMENT_STATUSES)} (Enter — залишити)",
        apt["status"],
    )
    if new_status not in APARTMENT_STATUSES:
        print("  ! Невірний статус")
        return
    update_apartment(conn, user["login"], aid, price=new_price, status=new_status)
    print("  ✓ Оновлено")


def delete_apartment_ui(conn, user):
    aid = prompt_int("ID квартири для видалення")
    if not get_apartment(conn, aid):
        print("  ! Не знайдено")
        return
    if confirm(f"Видалити квартиру ID={aid}"):
        try:
            delete_apartment(conn, user["login"], aid)
            print("  ✓ Видалено")
        except sqlite3.Error as exc:
            print(f"  ! Помилка: {exc}")


def apartments_menu(conn, user):
    while True:
        header("Квартири")
        print("  1. Список усіх")
        print("  2. Фільтр за статусом")
        print("  3. Пошук")
        print("  4. Сортування")
        print("  5. Додати квартиру")
        print("  6. Редагувати")
        print("  7. Видалити")
        print("  0. Назад")
        c = prompt("Вибір", "0")
        if c == "1":
            show_apartments(conn)
        elif c == "2":
            st = prompt(f"Статус ({'/'.join(APARTMENT_STATUSES)})", "available")
            if st in APARTMENT_STATUSES:
                show_apartments(conn, status=st)
            else:
                print("  ! Невірний статус")
        elif c == "3":
            show_apartments(conn, q=prompt("Пошук (номер/об'єкт)"))
        elif c == "4":
            show_apartments(conn, sort=prompt("Сортувати за (id/number/area/price/rooms)", "id"))
        elif c == "5":
            add_apartment_ui(conn, user)
        elif c == "6":
            edit_apartment_ui(conn, user)
        elif c == "7":
            delete_apartment_ui(conn, user)
        elif c == "0":
            return


def show_materials(conn, q=None):
    rows = list_materials(conn, q=q)
    data = [
        (r["id"], r["name"], r["unit"], f'{r["quantity"]:.2f}',
         fmt_money(r["price"]), r["supplier"] or "—")
        for r in rows
    ]
    print_table(["ID", "Назва", "Од.", "К-сть", "Ціна", "Постачальник"], data)


def materials_menu(conn, user):
    while True:
        header("Матеріали")
        print("  1. Список")
        print("  2. Пошук")
        print("  3. Додати")
        print("  4. Змінити кількість (прихід/видаток)")
        print("  5. Мало на складі")
        print("  0. Назад")
        c = prompt("Вибір", "0")
        if c == "1":
            show_materials(conn)
        elif c == "2":
            show_materials(conn, q=prompt("Частина назви"))
        elif c == "3":
            name = prompt("Назва")
            unit = prompt("Одиниця виміру", "шт")
            qty = prompt_float("Кількість", 0)
            price = prompt_float("Ціна", 0)
            sup_id = prompt_int("ID постачальника (Enter — без)", 0) or None
            add_material(conn, user["login"], name, unit, qty, price, sup_id)
            print("  ✓ Додано")
        elif c == "4":
            mid = prompt_int("ID матеріалу")
            delta = prompt_float("Зміна кількості (+ прихід, - видаток)")
            update_material_quantity(conn, user["login"], mid, delta)
            print("  ✓ Оновлено")
        elif c == "5":
            rows = low_stock_materials(conn)
            print_table(
                ["ID", "Назва", "Од.", "Залишок"],
                [(r["id"], r["name"], r["unit"], f'{r["quantity"]:.2f}') for r in rows],
            )
        elif c == "0":
            return


def clients_menu(conn, user):
    while True:
        header("Клієнти")
        print("  1. Список")
        print("  2. Пошук")
        print("  3. Додати")
        print("  0. Назад")
        c = prompt("Вибір", "0")
        if c == "1":
            rows = list_clients(conn)
            print_table(["ID", "ПІБ", "Телефон", "Email"],
                        [(r["id"], r["full_name"], r["phone"] or "—", r["email"] or "—")
                         for r in rows])
        elif c == "2":
            rows = list_clients(conn, q=prompt("Частина ПІБ"))
            print_table(["ID", "ПІБ", "Телефон", "Email"],
                        [(r["id"], r["full_name"], r["phone"] or "—", r["email"] or "—")
                         for r in rows])
        elif c == "3":
            cid = add_client(conn, user["login"], prompt("ПІБ"),
                             prompt("Телефон", ""), prompt("Email", ""))
            print(f"  ✓ Додано клієнта ID={cid}")
        elif c == "0":
            return


def sales_menu(conn, user):
    while True:
        header("Продажі")
        print("  1. Список продажів")
        print("  2. Оформити новий продаж")
        print("  0. Назад")
        c = prompt("Вибір", "0")
        if c == "1":
            rows = list_sales(conn)
            print_table(
                ["ID", "Дата", "Квартира", "Клієнт", "Сума"],
                [(r["id"], r["sale_date"], r["apt_number"],
                  r["client_name"], fmt_money(r["price"])) for r in rows],
            )
        elif c == "2":
            available = conn.execute(
                "SELECT id, number, price FROM apartments "
                "WHERE status = 'available' ORDER BY number"
            ).fetchall()
            if not available:
                print("  ! Немає доступних квартир")
                continue
            print("Доступні квартири:")
            for a in available:
                print(f"  {a['id']}. №{a['number']} — {fmt_money(a['price'])} UAH")
            apt_id = prompt_int("ID квартири")
            if not any(a["id"] == apt_id for a in available):
                print("  ! Некоректна квартира")
                continue
            clients = list_clients(conn)
            if not clients:
                print("  ! Спочатку додайте клієнта")
                continue
            print("Клієнти:")
            for cl in clients:
                print(f"  {cl['id']}. {cl['full_name']}")
            cli_id = prompt_int("ID клієнта")
            try:
                register_sale(conn, user["login"], apt_id, cli_id)
                print("  ✓ Продаж оформлено (статус квартири оновлено тригером БД)")
            except ValueError as exc:
                print(f"  ! {exc}")
        elif c == "0":
            return


def reports_menu(conn, user):
    while True:
        header("Звіти (для друку)")
        print("  1. Звіт про продажі")
        print("  2. Доступні квартири")
        print("  3. Матеріали з низьким запасом")
        print("  4. Повна інвентаризація матеріалів")
        print("  5. Всі клієнти")
        print("  0. Назад")
        c = prompt("Вибір", "0")
        if c == "1":
            rows = list_sales(conn)
            text = render_table(
                ["ID", "Дата", "Квартира", "Клієнт", "Сума"],
                [(r["id"], r["sale_date"], r["apt_number"],
                  r["client_name"], fmt_money(r["price"])) for r in rows],
            )
            total = sum(r["price"] for r in rows)
            print(text)
            print(f"\n  Всього продажів: {len(rows)}; Сума: {fmt_money(total)} UAH")
            if rows and confirm("Зберегти у файл"):
                save_report("sales", text + f"\nВсього: {fmt_money(total)} UAH\n")
        elif c == "2":
            rows = list_apartments(conn, status="available")
            text = render_table(
                ["ID", "Номер", "Об'єкт", "Площа", "Кімн.", "Ціна"],
                [(r["id"], r["number"], r["object_name"] or "—",
                  f'{r["area"]:.1f}', r["rooms"], fmt_money(r["price"])) for r in rows],
            )
            print(text)
            if rows and confirm("Зберегти у файл"):
                save_report("available_apartments", text + "\n")
        elif c == "3":
            rows = low_stock_materials(conn)
            text = render_table(
                ["ID", "Назва", "Од.", "Залишок"],
                [(r["id"], r["name"], r["unit"], f'{r["quantity"]:.2f}') for r in rows],
            )
            print(text)
            if rows and confirm("Зберегти у файл"):
                save_report("low_stock", text + "\n")
        elif c == "4":
            rows = list_materials(conn)
            text = render_table(
                ["ID", "Назва", "Од.", "К-сть", "Ціна", "Сума", "Постачальник"],
                [(r["id"], r["name"], r["unit"], f'{r["quantity"]:.2f}',
                  fmt_money(r["price"]),
                  fmt_money(r["quantity"] * r["price"]),
                  r["supplier"] or "—") for r in rows],
            )
            print(text)
            if rows and confirm("Зберегти у файл"):
                save_report("inventory", text + "\n")
        elif c == "5":
            rows = list_clients(conn)
            text = render_table(
                ["ID", "ПІБ", "Телефон", "Email"],
                [(r["id"], r["full_name"], r["phone"] or "—", r["email"] or "—")
                 for r in rows],
            )
            print(text)
            if rows and confirm("Зберегти у файл"):
                save_report("clients", text + "\n")
        elif c == "0":
            return


def statistics_menu(conn, user):
    header("Статистика")
    print("\n  [1] Розподіл квартир за статусом")
    rows = conn.execute(
        "SELECT status, COUNT(*) AS cnt FROM apartments GROUP BY status"
    ).fetchall()
    total = sum(r["cnt"] for r in rows) or 1
    for r in rows:
        print_bar(STATUS_LABELS.get(r["status"], r["status"]), r["cnt"], total)
        print(f"    {r['cnt']}/{total} ({r['cnt']*100//total}%)")
    print("\n  [2] Продажі по місяцях")
    rows = conn.execute(
        "SELECT substr(sale_date, 1, 7) AS ym, COUNT(*) AS cnt, "
        "SUM(price) AS total FROM sales GROUP BY ym ORDER BY ym"
    ).fetchall()
    if rows:
        max_total = max(r["total"] for r in rows)
        for r in rows:
            label = f"{r['ym']} ({r['cnt']} шт)"
            bar_len = int(round(r["total"] / max_total * BAR_WIDTH))
            print(f"  {label.ljust(LABEL_WIDTH)} | "
                  f"{'█' * bar_len} {fmt_money(r['total'])} UAH")
    else:
        print("    (немає даних)")
    print("\n  [3] Топ-5 матеріалів за залишком")
    rows = conn.execute(
        "SELECT name, quantity, unit FROM materials "
        "ORDER BY quantity DESC LIMIT 5"
    ).fetchall()
    if rows:
        max_q = max(r["quantity"] for r in rows) or 1
        for r in rows:
            print_bar(r["name"], r["quantity"], max_q)
            print(f"    {r['quantity']:.2f} {r['unit']}")
    else:
        print("    (немає даних)")
    print()


def log_view(conn, user, own_only=True):
    header("Журнал дій")
    if own_only:
        rows = conn.execute(
            "SELECT * FROM system_log WHERE user_login = ? ORDER BY id DESC LIMIT 30",
            (user["login"],),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM system_log ORDER BY id DESC LIMIT 100"
        ).fetchall()
    print_table(
        ["ID", "Час", "Користувач", "Дія", "Об'єкт", "ID", "Деталі"],
        [(r["id"], r["created_at"], r["user_login"] or "—",
          r["action"], r["entity"] or "—",
          r["entity_id"] or "—", (r["details"] or "")[:30]) for r in rows],
    )


def admin_list_users(conn):
    header("Користувачі")
    print_table(
        ["ID", "Логін", "Роль", "Активний", "Створено"],
        [(r["id"], r["login"], r["role_code"],
          "так" if r["is_active"] else "ні", r["created_at"]) for r in list_users(conn)],
    )


def admin_create_user(conn, user):
    login = prompt("Логін")
    password = prompt("Пароль")
    role = prompt("Роль (admin/manager/client)", "manager")
    if role not in (ROLE_ADMIN, ROLE_MANAGER, ROLE_CLIENT):
        print("  ! Невірна роль")
        return
    client_id = None
    if role == ROLE_CLIENT:
        cid = prompt_int("client_id (Enter — пропустити)", 0)
        client_id = cid or None
    try:
        uid = create_user(conn, user["login"], login, password, role, client_id)
        print(f"  ✓ Створено користувача ID={uid}")
    except sqlite3.Error as exc:
        print(f"  ! Помилка: {exc}")


def admin_toggle_user(conn, user):
    uid = prompt_int("ID користувача")
    toggle_user_active(conn, user["login"], uid)
    print("  ✓ Статус змінено")


def admin_view_log(conn):
    while True:
        header("Журнал системи")
        print("  1. Усі записи (100 останніх)")
        print("  2. Фільтр за користувачем")
        print("  3. Фільтр за дією (LOGIN/INSERT/UPDATE/DELETE/SALE)")
        print("  0. Назад")
        c = prompt("Вибір", "0")
        if c == "1":
            log_view(conn, {"login": ""}, own_only=False)
        elif c == "2":
            login = prompt("Логін")
            rows = conn.execute(
                "SELECT * FROM system_log WHERE user_login = ? ORDER BY id DESC LIMIT 100",
                (login,),
            ).fetchall()
            print_table(
                ["ID", "Час", "Дія", "Об'єкт", "ID", "Деталі"],
                [(r["id"], r["created_at"], r["action"],
                  r["entity"] or "—", r["entity_id"] or "—",
                  (r["details"] or "")[:30]) for r in rows],
            )
        elif c == "3":
            action = prompt("Дія").upper()
            rows = conn.execute(
                "SELECT * FROM system_log WHERE action = ? ORDER BY id DESC LIMIT 100",
                (action,),
            ).fetchall()
            print_table(
                ["ID", "Час", "Користувач", "Об'єкт", "ID"],
                [(r["id"], r["created_at"], r["user_login"] or "—",
                  r["entity"] or "—", r["entity_id"] or "—") for r in rows],
            )
        elif c == "0":
            return


def admin_settings(conn):
    header("Налаштування системи")
    rows = conn.execute("SELECT key, value FROM settings ORDER BY key").fetchall()
    print_table(["Ключ", "Значення"], [(r["key"], r["value"]) for r in rows])
    print("  1. Змінити low_stock_threshold")
    print("  2. Змінити currency")
    print("  0. Назад")
    c = prompt("Вибір", "0")
    if c == "1":
        set_setting(conn, "low_stock_threshold",
                    prompt_float("Нове значення", LOW_STOCK_DEFAULT))
        print("  ✓ Оновлено")
    elif c == "2":
        set_setting(conn, "currency", prompt("Валюта", DEFAULT_CURRENCY))
        print("  ✓ Оновлено")


def admin_menu(conn, user):
    while True:
        header("Адміністрування")
        print("  1. Список користувачів")
        print("  2. Створити користувача")
        print("  3. Активувати/деактивувати користувача")
        print("  4. Журнал системи")
        print("  5. Налаштування")
        print("  0. Назад")
        c = prompt("Вибір", "0")
        if c == "1":
            admin_list_users(conn)
        elif c == "2":
            admin_create_user(conn, user)
        elif c == "3":
            admin_toggle_user(conn, user)
        elif c == "4":
            admin_view_log(conn)
        elif c == "5":
            admin_settings(conn)
        elif c == "0":
            return


def help_screen():
    header("Довідка")
    print("""
  Призначення: облік квартир, матеріалів, клієнтів та продажів
  для будівельної фірми.

  Ролі:
    • admin    — повний доступ + адміністрування
    • manager  — ведення квартир, матеріалів, клієнтів, продажів
    • client   — гість: перегляд доступних квартир

  Гість (client) не потребує пароля — вхід через пункт 2 у меню входу.

  У будь-якому меню:
    • 0 — повернутися назад/вийти
    • Enter — прийняти значення за замовчуванням

  При оформленні продажу статус квартири стає "sold" автоматично
  через тригер бази даних trg_sale_marks_sold.
""")


def about_screen():
    header("Про програму")
    print(f"""
  Назва:        {APP_NAME}
  Версія:       {APP_VERSION}
  Номер збірки: {BUILD_NUMBER}
  Автор:        {AUTHOR}
  Група:        {GROUP}
  Призначення:  Облік діяльності будівельної фірми
  Стек:         Python 3, SQLite
""")


def menu_manager(user):
    conn = get_conn()
    try:
        while True:
            header(f"Менеджер — {user['login']}")
            for i, name in enumerate([
                "Квартири", "Матеріали", "Клієнти", "Продажі", "Звіти",
                "Статистика", "Журнал дій (мої)", "Довідка", "Про програму", "Вихід",
            ], 1):
                print(f"  {i if i < 10 else 0}. {name}")
            c = prompt("Вибір", "0")
            if c == "1": apartments_menu(conn, user)
            elif c == "2": materials_menu(conn, user)
            elif c == "3": clients_menu(conn, user)
            elif c == "4": sales_menu(conn, user)
            elif c == "5": reports_menu(conn, user)
            elif c == "6": statistics_menu(conn, user)
            elif c == "7": log_view(conn, user, own_only=True)
            elif c == "8": help_screen()
            elif c == "9": about_screen()
            elif c == "0":
                log_action(conn, user["login"], "LOGOUT")
                return
    finally:
        conn.close()


def menu_admin(user):
    conn = get_conn()
    try:
        while True:
            header(f"Адміністратор — {user['login']}")
            for i, name in enumerate([
                "Квартири", "Матеріали", "Клієнти", "Продажі", "Звіти",
                "Статистика", "Адміністрування", "Довідка", "Про програму", "Вихід",
            ], 1):
                print(f"  {i if i < 10 else 0}. {name}")
            c = prompt("Вибір", "0")
            if c == "1": apartments_menu(conn, user)
            elif c == "2": materials_menu(conn, user)
            elif c == "3": clients_menu(conn, user)
            elif c == "4": sales_menu(conn, user)
            elif c == "5": reports_menu(conn, user)
            elif c == "6": statistics_menu(conn, user)
            elif c == "7": admin_menu(conn, user)
            elif c == "8": help_screen()
            elif c == "9": about_screen()
            elif c == "0":
                log_action(conn, user["login"], "LOGOUT")
                return
    finally:
        conn.close()


def menu_client(user):
    conn = get_conn()
    try:
        while True:
            header(f"Гість — {user['login']}")
            print("  1. Доступні квартири")
            print("  2. Мої покупки")
            print("  3. Довідка")
            print("  4. Про програму")
            print("  0. Вихід")
            c = prompt("Вибір", "0")
            if c == "1":
                show_apartments(conn, status="available")
            elif c == "2":
                if not user.get("client_id"):
                    print("  Гість не має прив'язаного облікового запису клієнта.")
                    print("  Увійдіть як клієнт, щоб переглянути свої покупки.")
                else:
                    rows = client_sales(conn, user["client_id"])
                    print_table(
                        ["ID", "Дата", "Квартира", "Сума"],
                        [(r["id"], r["sale_date"], r["apt_number"],
                          fmt_money(r["price"])) for r in rows],
                    )
            elif c == "3":
                help_screen()
            elif c == "4":
                about_screen()
            elif c == "0":
                log_action(conn, user["login"], "LOGOUT")
                return
    finally:
        conn.close()


class BuildFirmTestCase(unittest.TestCase):
    """Unit-тести основних сервісів."""

    def setUp(self):
        if os.path.exists(DB_FILE):
            os.unlink(DB_FILE)
        init_db()
        self.conn = get_conn()

    def tearDown(self):
        self.conn.close()

    def test_password_hash_verify(self):
        h, s = hash_password("secret")
        self.assertTrue(verify_password("secret", h, s))
        self.assertFalse(verify_password("wrong", h, s))

    def test_seed_admin_exists(self):
        u = find_user(self.conn, "admin")
        self.assertIsNotNone(u)
        self.assertEqual(u["role_code"], ROLE_ADMIN)

    def test_add_apartment(self):
        aid = add_apartment(self.conn, "admin", 1, "999", 50.0, 2, 1_000_000.0)
        a = get_apartment(self.conn, aid)
        self.assertEqual(a["number"], "999")
        self.assertEqual(a["status"], "available")

    def test_register_sale_changes_status_via_trigger(self):
        apt = self.conn.execute(
            "SELECT id FROM apartments WHERE status = 'available' LIMIT 1"
        ).fetchone()
        register_sale(self.conn, "manager", apt["id"], 1)
        self.assertEqual(get_apartment(self.conn, apt["id"])["status"], "sold")

    def test_register_sale_twice_fails(self):
        apt = self.conn.execute(
            "SELECT id FROM apartments WHERE status = 'available' LIMIT 1"
        ).fetchone()
        register_sale(self.conn, "manager", apt["id"], 1)
        with self.assertRaises(ValueError):
            register_sale(self.conn, "manager", apt["id"], 1)

    def test_log_recorded_on_insert(self):
        add_apartment(self.conn, "admin", 1, "777", 40.0, 1, 800_000.0)
        logs = self.conn.execute(
            "SELECT * FROM system_log WHERE action='INSERT' AND entity='apartments'"
        ).fetchall()
        self.assertGreaterEqual(len(logs), 1)

    def test_low_stock_materials(self):
        rows = low_stock_materials(self.conn, threshold=100)
        self.assertGreaterEqual(len(rows), 1)


def run_tests():
    """Запускає тести у тимчасовій БД."""
    global DB_FILE
    tmpdir = tempfile.mkdtemp(prefix="buildfirm_")
    original = DB_FILE
    DB_FILE = os.path.join(tmpdir, "test.db")
    try:
        suite = unittest.TestLoader().loadTestsFromTestCase(BuildFirmTestCase)
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        return 0 if result.wasSuccessful() else 1
    finally:
        DB_FILE = original
        try:
            os.unlink(os.path.join(tmpdir, "test.db"))
        except OSError:
            pass
        try:
            os.rmdir(tmpdir)
        except OSError:
            pass


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass
    if "--test" in sys.argv:
        sys.exit(run_tests())
    init_db()
    user = login_screen()
    if user is None:
        return
    role = user["role_code"]
    if role == ROLE_ADMIN:
        menu_admin(user)
    elif role == ROLE_MANAGER:
        menu_manager(user)
    elif role == ROLE_CLIENT:
        menu_client(user)
    else:
        print(f"Невідома роль: {role}")


if __name__ == "__main__":
    main()