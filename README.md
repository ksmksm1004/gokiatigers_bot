# gokiatigers_bot

KIA 타이거즈 경기만 감시하는 네이버 스포츠 JSON API 기반 텔레그램 중계 봇입니다.

## 설정

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

`.env`를 열어 아래 값을 채워주세요.

```bash
TELEGRAM_TOKEN=botfather_token
TELEGRAM_CHAT_ID={YOUR_CHAT_ID}
TEAM_CODE=HT
```

자동 경기 검색이 실패하면 당일 경기 ID를 직접 고정할 수 있습니다.

```bash
NAVER_GAME_ID=20260702SKHT02026
```

## 실행

테스트 발송 없이 메시지 내용을 콘솔에서 확인:

```bash
DRY_RUN=1 python3 bot.py
```

백그라운드 실행:

```bash
nohup python3 bot.py > logs/nohup.out 2>&1 &
```

## macOS LaunchAgent 등록

재부팅 후에도 봇을 자동 실행하려면 앱용 디렉터리로 옮긴 뒤 가상환경을 다시 만듭니다.

```bash
APP_DIR="$HOME/apps/gokiatigers_bot"

mkdir -p "$HOME/apps"
mv /path/to/gokiatigers_bot "$APP_DIR"
cd "$APP_DIR"

rm -rf .venv
python3 -m venv .venv
source .venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt
```

certifi CA 경로를 확인합니다. plist의 `SSL_CERT_FILE`, `REQUESTS_CA_BUNDLE` 값은 이 출력과 같아야 합니다.

```bash
"$APP_DIR/.venv/bin/python3" -c "import certifi; print(certifi.where())"
```

`~/Library/LaunchAgents/com.gokiatigers.bot.plist`를 생성합니다. 아래의 `/Users/YOUR_USER/apps/gokiatigers_bot`와 CA 경로의 `python3.9` 부분은 본인 환경에 맞게 바꿔주세요. `~`와 `$HOME`은 plist 안에서 자동 확장되지 않으므로 절대 경로를 써야 합니다.

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">

<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.gokiatigers.bot</string>

    <key>ProgramArguments</key>
    <array>
        <string>/Users/YOUR_USER/apps/gokiatigers_bot/.venv/bin/python3</string>
        <string>/Users/YOUR_USER/apps/gokiatigers_bot/bot.py</string>
    </array>

    <key>WorkingDirectory</key>
    <string>/Users/YOUR_USER/apps/gokiatigers_bot</string>

    <key>StandardOutPath</key>
    <string>/Users/YOUR_USER/apps/gokiatigers_bot/logs/launchd.out</string>

    <key>StandardErrorPath</key>
    <string>/Users/YOUR_USER/apps/gokiatigers_bot/logs/launchd.err</string>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <true/>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PYTHONUNBUFFERED</key>
        <string>1</string>
        <key>SSL_CERT_FILE</key>
        <string>/Users/YOUR_USER/apps/gokiatigers_bot/.venv/lib/python3.9/site-packages/certifi/cacert.pem</string>
        <key>REQUESTS_CA_BUNDLE</key>
        <string>/Users/YOUR_USER/apps/gokiatigers_bot/.venv/lib/python3.9/site-packages/certifi/cacert.pem</string>
    </dict>
</dict>
</plist>
```

plist 문법과 권한을 확인한 뒤 등록합니다.

```bash
plutil -lint ~/Library/LaunchAgents/com.gokiatigers.bot.plist
chmod 644 ~/Library/LaunchAgents/com.gokiatigers.bot.plist
chown $(id -un):staff ~/Library/LaunchAgents/com.gokiatigers.bot.plist
mkdir -p "$APP_DIR/logs"

launchctl bootout gui/$(id -u)/com.gokiatigers.bot 2>/dev/null
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.gokiatigers.bot.plist 2>/dev/null
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.gokiatigers.bot.plist
launchctl kickstart -k gui/$(id -u)/com.gokiatigers.bot
```

상태와 로그 확인:

```bash
launchctl print gui/$(id -u)/com.gokiatigers.bot
ps aux | grep gokiatigers_bot | grep -v grep
tail -f "$APP_DIR/logs/bot.log"
tail -f "$APP_DIR/logs/launchd.err"
```

코드 변경 후 다시 실행:

```bash
cd "$APP_DIR"
source .venv/bin/activate
pip install -r requirements.txt
python3 -m py_compile bot.py parser.py telegram.py naver_api.py naver_weather.py
python3 -m unittest discover -p "test_*.py"

launchctl kickstart -k gui/$(id -u)/com.gokiatigers.bot
```

`Bootstrap failed: 5`가 나오면 보통 plist 문법, 권한, 이미 등록된 job 문제입니다.

```bash
plutil -lint ~/Library/LaunchAgents/com.gokiatigers.bot.plist
launchctl bootout gui/$(id -u)/com.gokiatigers.bot 2>/dev/null
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.gokiatigers.bot.plist 2>/dev/null
log show --predicate 'process == "launchd"' --last 2m | grep gokiatigers
```

이전 경로 프로세스가 남아 있으면 종료합니다.

```bash
pkill -f "/old/path/to/gokiatigers_bot/bot.py"
pkill -f "/old/path/to/gokiatigers_bot/.venv"
```

## 동작

- 오늘 KIA 경기 일정을 찾고 `logs/state.json`에 캐시합니다.
- 경기 없는 날은 기본 6시간마다 일정만 확인합니다.
- 경기 전에는 기본 5분마다 프리뷰/라인업 상태만 확인합니다.
- 경기 시작 후에만 5초마다 릴레이를 확인합니다.
- 경기 시작 60분 전부터 프리뷰, 순위, 최근 5경기, 상대전적, 선발투수를 보냅니다.
- 선발 라인업이 발표되면 양팀 선발투수와 1~9번 타자를 선수 사진, 순번, 포지션과 함께 한 번 보냅니다.
- KIA 공격 시작 때 예상 타자 3명과 현재 타수/안타를 보냅니다.
- KIA 타자의 안타, 사사구, 희생플라이, 도루와 득점 이벤트, 투수 교체, 경기 종료를 텔레그램으로 보냅니다.
- KIA 타자의 진루 결과는 네이버 선수 이미지 URL을 `sendPhoto`로 함께 보냅니다.
- 경기 종료 후 KIA 기록, 경기 하이라이트, KBO 전체 순위와 최근 10경기 성적을 보냅니다.
- `/라인업`, `/기록`, `/순위`, `/날씨`, `/gg`, `/re`, `/도움말` 명령을 지원합니다.
- 텔레그램 명령 메뉴에는 `/lineup`, `/record`, `/rank`, `/weather`, `/gg`, `/re`, `/help` 영문 명령이 등록됩니다.
- `logs/state.json`에 마지막 릴레이 번호를 저장해 재시작 후 중복 발송을 줄입니다.

## 주의

텔레그램 토큰은 절대 커밋하지 마세요. 
