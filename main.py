import asyncio
import logging
from datetime import datetime
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message
import subprocess
import platform
from config import BOT_TOKEN, CHAT_ID, TARGET_IP, CHECK_INTERVAL

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Инициализация бота
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Глобальные переменные для отслеживания состояния
is_monitoring = False
last_status = None
consecutive_failures = 0


def ping_host(host: str, timeout: int = 2) -> tuple[bool, float]:
    """
    Пингует хост и возвращает кортеж (доступен, время_пинга_мс)
    """
    try:
        # Определяем параметры в зависимости от ОС
        param = '-n' if platform.system().lower() == 'windows' else '-c'
        timeout_param = '-w' if platform.system().lower() == 'windows' else '-W'
        
        # Выполняем ping команду
        command = ['ping', param, '1', timeout_param, str(timeout), host]
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout + 1,
            text=True
        )
        
        if result.returncode == 0:
            # Парсим время пинга из вывода
            ping_time = parse_ping_time(result.stdout)
            return True, ping_time
        else:
            return False, 0.0
            
    except subprocess.TimeoutExpired:
        logger.warning(f"Ping timeout для {host}")
        return False, 0.0
    except Exception as e:
        logger.error(f"Ошибка при пинге {host}: {e}")
        return False, 0.0


def parse_ping_time(output: str) -> float:
    """
    Парсит время пинга из вывода команды ping
    """
    import re
    
    try:
        # Для Linux: time=15.2 ms
        match = re.search(r'time[=<](\d+\.?\d*)\s*ms', output, re.IGNORECASE)
        if match:
            return float(match.group(1))
        
        # Для Windows: time=15ms или time<1ms
        match = re.search(r'time[=<](\d+)', output, re.IGNORECASE)
        if match:
            return float(match.group(1))
            
    except Exception as e:
        logger.error(f"Ошибка парсинга времени пинга: {e}")
    
    return 0.0


async def check_host():
    """
    Проверяет доступность хоста и отправляет уведомления
    """
    global last_status, consecutive_failures
    
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    is_online, ping_time = ping_host(TARGET_IP)
    
    # Если статус изменился
    if last_status != is_online:
        if not is_online:
            # Хост стал недоступен
            message = (
                f"⚠️ <b>ВНИМАНИЕ!</b>\n\n"
                f"IP-адрес <code>{TARGET_IP}</code> недоступен!\n"
                f"Время: {current_time}"
            )
            consecutive_failures = 1
            await bot.send_message(CHAT_ID, message, parse_mode="HTML")
            logger.warning(f"Хост {TARGET_IP} недоступен")
        else:
            # Хост снова доступен
            ping_display = f"{ping_time:.1f} ms" if ping_time > 0 else "N/A"
            message = (
                f"✅ <b>Восстановлено</b>\n\n"
                f"IP-адрес <code>{TARGET_IP}</code> снова доступен!\n"
                f"Пинг: <b>{ping_display}</b>\n"
                f"Время: {current_time}\n"
                f"Было недоступно попыток: {consecutive_failures}"
            )
            consecutive_failures = 0
            await bot.send_message(CHAT_ID, message, parse_mode="HTML")
            logger.info(f"Хост {TARGET_IP} восстановлен, пинг: {ping_time:.1f}ms")
        
        last_status = is_online
    else:
        # Статус не изменился
        if not is_online:
            consecutive_failures += 1
            # Отправляем напоминание каждые 10 неудачных попыток (5 минут)
            if consecutive_failures % 10 == 0:
                message = (
                    f"⚠️ <b>Напоминание</b>\n\n"
                    f"IP-адрес <code>{TARGET_IP}</code> всё ещё недоступен!\n"
                    f"Время: {current_time}\n"
                    f"Неудачных попыток подряд: {consecutive_failures}"
                )
                await bot.send_message(CHAT_ID, message, parse_mode="HTML")


async def monitoring_loop():
    """
    Основной цикл мониторинга
    """
    global is_monitoring
    
    logger.info(f"Запуск мониторинга IP: {TARGET_IP}")
    
    # Проверяем начальный статус
    is_online, ping_time = ping_host(TARGET_IP)
    status_icon = "✅" if is_online else "❌"
    status_text = "доступен" if is_online else "недоступен"
    
    start_message = f"🤖 <b>Бот запущен!</b>\n\n"
    start_message += f"IP: <code>{TARGET_IP}</code>\n"
    start_message += f"Статус: {status_icon} {status_text}\n"
    
    if is_online and ping_time > 0:
        start_message += f"Пинг: <b>{ping_time:.1f} ms</b>\n"
    
    start_message += f"Интервал проверки: {CHECK_INTERVAL} секунд"
    
    await bot.send_message(CHAT_ID, start_message, parse_mode="HTML")
    
    while is_monitoring:
        try:
            await check_host()
            await asyncio.sleep(CHECK_INTERVAL)
        except Exception as e:
            logger.error(f"Ошибка в цикле мониторинга: {e}")
            await asyncio.sleep(CHECK_INTERVAL)


@dp.message(Command("start"))
async def cmd_start(message: Message):
    """
    Обработчик команды /start
    """
    global is_monitoring
    
    if not is_monitoring:
        is_monitoring = True
        await message.answer(
            "🤖 Бот мониторинга IP запущен!\n\n"
            f"Отслеживаемый IP: <code>{TARGET_IP}</code>\n"
            f"Интервал проверки: {CHECK_INTERVAL} секунд\n\n"
            "Команды:\n"
            "/status - текущий статус\n"
            "/stop - остановить мониторинг",
            parse_mode="HTML"
        )
        # Запускаем мониторинг в фоне
        asyncio.create_task(monitoring_loop())
    else:
        await message.answer("⚠️ Мониторинг уже запущен!")


@dp.message(Command("stop"))
async def cmd_stop(message: Message):
    """
    Обработчик команды /stop
    """
    global is_monitoring
    
    if is_monitoring:
        is_monitoring = False
        await message.answer("🛑 Мониторинг остановлен")
        logger.info("Мониторинг остановлен пользователем")
    else:
        await message.answer("⚠️ Мониторинг не запущен")


@dp.message(Command("status"))
async def cmd_status(message: Message):
    """
    Обработчик команды /status - показывает текущий статус
    """
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    is_online, ping_time = ping_host(TARGET_IP)
    
    status_icon = "✅" if is_online else "❌"
    status_text = "доступен" if is_online else "недоступен"
    
    # Форматируем отображение пинга
    if is_online and ping_time > 0:
        ping_display = f"<b>{ping_time:.1f} ms</b>"
        # Добавляем индикатор качества соединения
        if ping_time < 50:
            quality = "🟢 отличный"
        elif ping_time < 100:
            quality = "🟡 хороший"
        elif ping_time < 200:
            quality = "🟠 средний"
        else:
            quality = "🔴 медленный"
        ping_info = f"Пинг: {ping_display} ({quality})\n"
    else:
        ping_info = ""
    
    status_message = (
        f"📊 <b>Текущий статус</b>\n\n"
        f"IP: <code>{TARGET_IP}</code>\n"
        f"Статус: {status_icon} {status_text}\n"
        f"{ping_info}"
        f"Время проверки: {current_time}\n"
        f"Мониторинг: {'🟢 активен' if is_monitoring else '🔴 остановлен'}\n"
        f"Неудачных попыток подряд: {consecutive_failures}"
    )
    
    await message.answer(status_message, parse_mode="HTML")


async def main():
    """
    Главная функция запуска бота
    """
    global is_monitoring
    
    logger.info("Запуск бота...")
    
    # Автоматически запускаем мониторинг при старте
    is_monitoring = True
    
    # Запускаем мониторинг и polling одновременно
    monitoring_task = asyncio.create_task(monitoring_loop())
    
    try:
        await dp.start_polling(bot)
    finally:
        is_monitoring = False
        monitoring_task.cancel()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен")
