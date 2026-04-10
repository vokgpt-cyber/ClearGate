# Backup Strategy — VELUM

## Что бэкапится и зачем

| Что | Куда | Зачем |
|-----|------|-------|
| Git история | `.bundle` файл | Полное восстановление кода + всей истории разработки |
| Рабочая директория (без моделей и venv) | `.7z` архив | Конфиги, документация, незакоммиченные изменения, .env (если зашифровано) |
| ❌ ML модели | НЕ бэкапится | Десятки ГБ, легко перекачивается через `download-models.ps1` |
| ❌ node_modules / .venv | НЕ бэкапится | Восстанавливается через `npm install` / `pip install -e .[dev]` |

## GFS-ротация (Grandfather-Father-Son)

Стандартная схема, обеспечивающая баланс между retention и местом на диске:

| Уровень | Сколько хранится | Когда создаётся |
|---------|------------------|-----------------|
| **Daily** | 7 (по умолчанию) | При каждом запуске backup.ps1 |
| **Weekly** | 4 | По воскресеньям, копией дневного |
| **Monthly** | 12 | 1-го числа каждого месяца, копией дневного |

Итого: ~23 архивных слепка на любой момент времени.

## Расписание бэкапов

### Ручной бэкап (рекомендуется)
Запускать **перед каждой серьёзной задачей** и **в конце каждого рабочего дня**:
```powershell
.\scripts\backup.ps1
```

### Автоматический по расписанию
Через Windows Task Scheduler:
```powershell
# Создать задачу на ежедневный запуск в 22:00
$action = New-ScheduledTaskAction -Execute "pwsh.exe" `
    -Argument "-NoProfile -File D:\Projects\velum\scripts\backup.ps1"
$trigger = New-ScheduledTaskTrigger -Daily -At 10pm
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERNAME" -LogonType S4U
Register-ScheduledTask -TaskName "VELUM Daily Backup" `
    -Action $action -Trigger $trigger -Principal $principal
```

### Через Claude Code slash command
```
/backup-now
```

## Хранение

### Локально
- **Основное место**: внешний SSD (`D:\Backups\VELUM`)
- **Резервное**: NAS или второй внешний диск
- **Никогда**: не хранить только на том же диске, что и проект

### Облако (опционально)
Если используется облачная синхронизация (OneDrive, Google Drive, Яндекс.Диск):
- **Только зашифрованные** бэкапы
- Папка `monthly/` → синхронизация в облако (12 архивов по году)
- Папка `daily/` → НЕ синхронизировать (создаёт лишний трафик)

⚠️ **Никогда не загружать незашифрованные бэкапы в облако** — они содержат `.env` с API ключами.

## Шифрование

```powershell
# Включить шифрование (запросит пароль)
.\scripts\backup.ps1 -Encrypt

# Или установить пароль в env переменной (для автоматизации)
$env:VELUM_BACKUP_PASSPHRASE = "your-strong-passphrase"
.\scripts\backup.ps1 -Encrypt
```

Используется AES-256 через 7-Zip (`-mhe=on` шифрует и заголовки архива).

⚠️ **Master key и passphrase backups храните отдельно** от основных бэкапов: парольный менеджер, бумажный backup в сейфе. Если потеряете пароль — данные не восстановить.

## Проверка целостности

```powershell
# Git fsck выполняется автоматически перед каждым бэкапом
# Можно запустить вручную:
git -C D:\Projects\velum fsck --full

# Проверить bundle:
git bundle verify D:\Backups\VELUM\daily\velum_2026-04-09_18-00-00.bundle
```

## Восстановление

См. также `scripts/restore-backup.ps1`.

### Из bundle (только git история)
```powershell
git clone D:\Backups\VELUM\daily\velum_2026-04-09_18-00-00.bundle D:\Restored\velum
cd D:\Restored\velum
git checkout main
```

### Из 7z архива (полное состояние рабочей директории)
```powershell
.\scripts\restore-backup.ps1 `
    -BackupPath "D:\Backups\VELUM\daily\velum_2026-04-09_18-00-00.7z" `
    -TargetDir "D:\Restored\velum"

cd D:\Restored\velum
.\scripts\setup-dev.ps1
.\scripts\download-models.ps1 -Profile alpha
```

### Из зашифрованного бэкапа
```powershell
.\scripts\restore-backup.ps1 `
    -BackupPath "D:\Backups\VELUM\daily\velum_2026-04-09_18-00-00.7z.enc" `
    -TargetDir "D:\Restored\velum" `
    -Decrypt
# Запросит passphrase
```

## Disaster Recovery — план восстановления

| Сценарий | Действия | RTO | RPO |
|----------|----------|-----|-----|
| Случайно удалил файл | `git checkout HEAD~1 -- path/to/file` | 1 мин | 0 |
| Испортил коммит | `git reset --hard HEAD~N` | 5 мин | 0 |
| Сломал репо (corrupted .git) | `git clone <last bundle>` | 15 мин | <24 ч |
| Сгорел SSD ноутбука | Restore с внешнего диска → setup-dev → download-models | 2 ч | <24 ч |
| Сгорел весь дом | Restore из облачного monthly бэкапа | 4 ч | <30 дней |

**RTO** (Recovery Time Objective) — за сколько восстановить
**RPO** (Recovery Point Objective) — сколько работы потеряем

## Тестирование бэкапов

⚠️ **Бэкап, который никогда не восстанавливался — это не бэкап.**

Раз в месяц:
1. Распакуй последний weekly бэкап в тестовую папку
2. Проверь, что `setup-dev.ps1` работает
3. Проверь, что pytest и npm test проходят
4. Проверь, что git история целая (`git log --oneline | wc -l`)

Зафиксируй результат теста в `docs/BACKUP_TESTS.md` (создаётся при необходимости).

## Что делать при потере пароля от шифрования

К сожалению, ничего. AES-256 не поддаётся брутфорсу за разумное время.

**Поэтому**:
- Храни passphrase в нескольких местах (KeePass + бумажная копия в сейфе)
- Используй одну passphrase для всех бэкапов проекта (не разные на каждый день)
- При смене passphrase — расшифруй старые бэкапы и зашифруй новой
