"""
Запускает scooter_bot и multitool_bot одновременно в отдельных процессах.
Используется как единая точка входа для деплоя (Railway worker).
"""
import multiprocessing
import sys
import time


def run_scooter():
    import scooter_bot
    scooter_bot.main()


def run_multitool():
    import multitool_bot
    multitool_bot.main()


def main():
    processes = [
        multiprocessing.Process(target=run_scooter, name="scooter_bot"),
        multiprocessing.Process(target=run_multitool, name="multitool_bot"),
    ]

    for p in processes:
        p.start()
        print(f"✅ Запущен процесс: {p.name} (pid={p.pid})")

    # Если один из процессов упадёт — перезапускаем его, чтобы второй бот не тянул за собой первый
    try:
        while True:
            for i, p in enumerate(processes):
                if not p.is_alive():
                    print(f"⚠️ Процесс {p.name} упал, перезапускаю...")
                    target = run_scooter if p.name == "scooter_bot" else run_multitool
                    new_p = multiprocessing.Process(target=target, name=p.name)
                    new_p.start()
                    processes[i] = new_p
            time.sleep(5)
    except KeyboardInterrupt:
        for p in processes:
            p.terminate()
        sys.exit(0)


if __name__ == "__main__":
    main()
