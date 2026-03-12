#!/usr/bin/env python3
"""
Пошаговое руководство по тестированию Zepp MCP с реальными данными.

Шаги:
1. Экспортировать данные из приложения
2. Запустить этот скрипт с путём к экспортированным данным
3. Проверить, что всё работает
"""

import sys
from pathlib import Path

# Добавляем src в путь
sys.path.insert(0, str(Path(__file__).parent / "src"))

from zepp_life_mcp.adapters.export_file import ExportFileAdapter


def main():
    print("=" * 70)
    print("Zepp MCP - Тестирование с реальными данными")
    print("=" * 70)
    print()
    
    if len(sys.argv) < 2:
        print("❌ Ошибка: Не указан путь к экспортированным данным")
        print()
        print("Использование:")
        print(f"  python {sys.argv[0]} <путь_к_папке_с_экспортом>")
        print()
        print("Пример:")
        print(f"  python {sys.argv[0]} ~/Downloads/ZeppExport")
        print()
        print("Как получить данные:")
        print()
        print("  Вариант 1 - Через приложение Zepp Life:")
        print("    1. Откройте Zepp Life")
        print("    2. Profile → Settings → Account & Security")
        print("    3. Delete Account → Export Data")
        print("    4. Дождитесь email (5-30 минут)")
        print("    5. Скачайте и распакуйте архив")
        print()
        print("  Вариант 2 - Через веб-интерфейс:")
        print("    1. Откройте https://user.huami.com/privacy/index.html")
        print("    2. Авторизуйтесь")
        print("    3. Нажмите 'Export data'")
        print("    4. Скачайте архив")
        print()
        sys.exit(1)
    
    export_path = Path(sys.argv[1])
    
    print(f"📁 Проверка пути: {export_path}")
    
    if not export_path.exists():
        print(f"   ❌ Папка не существует: {export_path}")
        sys.exit(1)
    
    print(f"   ✅ Папка найдена")
    print()
    
    # Подключаем адаптер
    print("🔌 Подключение к данным...")
    adapter = ExportFileAdapter(export_path)
    connected = adapter.connect()
    
    if not connected:
        print("   ❌ Не удалось подключиться к данным")
        print("   Возможные причины:")
        print("   - Папка пуста или не содержит CSV/JSON файлов")
        print("   - Файлы имеют неожиданный формат")
        print("   - Нет прав на чтение")
        sys.exit(1)
    
    print(f"   ✅ Подключено успешно")
    print(f"   👤 User ID: {adapter.get_user_id()}")
    print()
    
    # Проверяем доступные типы данных
    available_types = adapter.get_available_data_types()
    print(f"📊 Найденные типы данных ({len(available_types)}):")
    
    if not available_types:
        print("   ⚠️  Не найдено данных")
        print("   Убедитесь, что в папке есть CSV или JSON файлы")
    
    for data_type in available_types:
        print(f"   • {data_type}")
    
    print()
    
    # Считаем записи
    print("📈 Подсчёт записей:")
    
    if "daily_activity" in available_types:
        count = sum(1 for _ in adapter.iter_daily_activity())
        print(f"   Шаги/активность: {count} записей")
        
        # Показываем пример
        activities = list(adapter.iter_daily_activity())[:3]
        if activities:
            print("   Примеры:")
            for a in activities:
                print(f"     {a.date}: {a.steps} шагов, {a.distance_m}м")
    
    if "sleep" in available_types:
        count = sum(1 for _ in adapter.iter_sleep_sessions())
        print(f"   Сон: {count} записей")
    
    if "workouts" in available_types:
        count = sum(1 for _ in adapter.iter_workouts())
        print(f"   Тренировки: {count} записей")
        
        # Показываем пример
        workouts = list(adapter.iter_workouts())[:3]
        if workouts:
            print("   Примеры:")
            for w in workouts:
                dist = f", {w.distance_m}м" if w.distance_m else ""
                print(f"     {w.activity_type}: {w.duration_minutes} мин{dist}")
    
    if "body_measurements" in available_types:
        count = sum(1 for _ in adapter.iter_body_measurements())
        print(f"   Вес/состав тела: {count} записей")
    
    print()
    print("=" * 70)
    print("✅ Тест пройден успешно!")
    print("=" * 70)
    print()
    print("Теперь вы можете:")
    print("  1. Настроить MCP сервер:")
    print(f"     python -m zepp_life_mcp.main setup")
    print()
    print("  2. Запустить сервер:")
    print(f"     ZEPP_EXPORT_PATH={export_path} python -m zepp_life_mcp.main serve")
    print()
    print("  3. Добавить в Claude Desktop config:")
    print()
    print('  {')
    print('    "mcpServers": {')
    print('      "zepp-life": {')
    print(f'        "command": "{sys.executable}",')
    print('        "args": ["-m", "zepp_life_mcp.main", "serve"],')
    print('        "env": {')
    print(f'          "ZEPP_EXPORT_PATH": "{export_path}"')
    print('        }')
    print('      }')
    print('    }')
    print('  }')


if __name__ == "__main__":
    main()
